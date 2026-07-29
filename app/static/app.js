// Frontend do ConciliaFlow: uma página, sem build step.
// Consome a mesma API pública documentada em /docs — nada de rota especial
// para a tela.

const $ = (sel) => document.querySelector(sel);
const FONTES = [
  ["a", "Fonte A — sistema interno", true],
  ["b", "Fonte B — extrato", true],
  ["c", "Fonte C — opcional", false],
];

let jobAtual = null;

// --- utilidades ------------------------------------------------------------

async function api(rota, opcoes = {}) {
  const resposta = await fetch(rota, opcoes);
  if (!resposta.ok) {
    let detalhe = `${resposta.status}`;
    try {
      const corpo = await resposta.json();
      detalhe = typeof corpo.detail === "string" ? corpo.detail : JSON.stringify(corpo.detail);
    } catch (_) { /* resposta sem JSON */ }
    throw new Error(detalhe);
  }
  return resposta.status === 204 ? null : resposta.json();
}

let avisoTimer;
function avisar(texto, falhou = false) {
  const caixa = $("#aviso");
  caixa.textContent = texto;
  caixa.classList.toggle("falha", falhou);
  caixa.hidden = false;
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => { caixa.hidden = true; }, falhou ? 8000 : 3500);
}

const brl = (valor) =>
  valor === null || valor === undefined
    ? "—"
    : Number(valor).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const dia = (iso) => (iso ? iso.split("-").reverse().join("/") : "—");

function celula(texto, classe) {
  const td = document.createElement("td");
  td.textContent = texto;
  if (classe) td.className = classe;
  return td;
}

// --- tela de execuções -----------------------------------------------------

async function carregarJobs() {
  const jobs = await api("/jobs/");
  const corpo = $("#tabela-jobs tbody");
  corpo.textContent = "";

  for (const job of jobs) {
    const tr = document.createElement("tr");
    tr.appendChild(celula(job.id, "mono"));

    const nome = document.createElement("td");
    const link = document.createElement("a");
    link.className = "linha-job";
    link.textContent = job.name;
    link.onclick = () => abrirJob(job.id);
    nome.appendChild(link);
    tr.appendChild(nome);

    const status = document.createElement("td");
    status.appendChild(etiqueta(job.status));
    tr.appendChild(status);

    tr.appendChild(celula(new Date(job.created_at).toLocaleString("pt-BR")));

    const acao = document.createElement("td");
    const apagar = document.createElement("button");
    apagar.className = "secundario";
    apagar.textContent = "Apagar";
    apagar.onclick = async () => {
      if (!confirm(`Apagar a execução "${job.name}" e todos os registros dela?`)) return;
      await api(`/jobs/${job.id}`, { method: "DELETE" });
      avisar("Execução apagada.");
      carregarJobs();
    };
    acao.appendChild(apagar);
    tr.appendChild(acao);

    corpo.appendChild(tr);
  }

  $("#jobs-vazio").hidden = jobs.length > 0;
  $("#tabela-jobs").hidden = jobs.length === 0;
}

function etiqueta(texto) {
  const span = document.createElement("span");
  span.className = `etiqueta ${texto}`;
  span.textContent = texto;
  return span;
}

$("#btn-nova").onclick = () => { $("#form-job").hidden = false; };
$("#btn-cancelar").onclick = () => { $("#form-job").hidden = true; };

$("#form-job").onsubmit = async (evento) => {
  evento.preventDefault();
  const dados = Object.fromEntries(new FormData(evento.target));
  try {
    const job = await api("/jobs/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: dados.name,
        description: dados.description || null,
        date_window_days: Number(dados.date_window_days),
        amount_tolerance_cents: Number(dados.amount_tolerance_cents),
      }),
    });
    evento.target.reset();
    $("#form-job").hidden = true;
    abrirJob(job.id);
  } catch (erro) {
    avisar(`Não deu para criar: ${erro.message}`, true);
  }
};

// --- tela de detalhe -------------------------------------------------------

function mostrarTela(qual) {
  $("#tela-jobs").hidden = qual !== "jobs";
  $("#tela-detalhe").hidden = qual !== "detalhe";
}

$("#btn-voltar").onclick = () => {
  jobAtual = null;
  mostrarTela("jobs");
  carregarJobs();
};

async function abrirJob(id) {
  jobAtual = await api(`/jobs/${id}`);
  mostrarTela("detalhe");

  $("#detalhe-nome").textContent = jobAtual.name;
  const status = $("#detalhe-status");
  status.className = `etiqueta ${jobAtual.status}`;
  status.textContent = jobAtual.status;

  $("#form-parametros [name=date_window_days]").value = jobAtual.date_window_days;
  $("#form-parametros [name=amount_tolerance_cents]").value = jobAtual.amount_tolerance_cents;

  desenharFontes();
  desenharResumo();
  if (jobAtual.summary_json) carregarMatches();
  else $("#resultados").hidden = true;
}

function desenharFontes() {
  const caixa = $("#fontes");
  caixa.textContent = "";
  const porFonte = Object.fromEntries((jobAtual.sources || []).map((s) => [s.source, s]));

  for (const [lado, titulo, obrigatoria] of FONTES) {
    const info = porFonte[lado];
    const div = document.createElement("div");
    div.className = "fonte";

    const h4 = document.createElement("h4");
    h4.textContent = titulo + (obrigatoria ? "" : " (não entra na conciliação)");
    div.appendChild(h4);

    const arquivo = document.createElement("p");
    arquivo.className = "arquivo";
    arquivo.textContent = info && info.filename
      ? `${info.filename} — ${info.rows} linhas, ${info.rows_with_error} com erro, ${brl(info.total_amount)}`
      : "nenhum arquivo enviado";
    if (info && info.rows_with_error > 0) arquivo.classList.add("erro-linha");
    div.appendChild(arquivo);

    const entrada = document.createElement("input");
    entrada.type = "file";
    entrada.accept = ".csv,.xlsx,.xls,text/csv";
    entrada.onchange = () => enviarArquivo(lado, entrada.files[0]);
    div.appendChild(entrada);

    caixa.appendChild(div);
  }
}

async function enviarArquivo(lado, arquivo) {
  if (!arquivo) return;
  const corpo = new FormData();
  corpo.append("file", arquivo);
  try {
    const resultado = await api(`/jobs/${jobAtual.id}/upload/${lado}`, {
      method: "POST",
      body: corpo,
    });
    const detectadas = Object.keys(resultado.detected_mapping).join(", ") || "nenhuma";
    avisar(
      `${resultado.rows_imported} linhas importadas` +
      (resultado.rows_with_error ? `, ${resultado.rows_with_error} com erro` : "") +
      ` · colunas detectadas: ${detectadas}`
    );
    abrirJob(jobAtual.id);
  } catch (erro) {
    avisar(`Falha no upload: ${erro.message}`, true);
  }
}

$("#form-parametros").onsubmit = async (evento) => {
  evento.preventDefault();
  const dados = Object.fromEntries(new FormData(evento.target));
  try {
    await api(`/jobs/${jobAtual.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date_window_days: Number(dados.date_window_days),
        amount_tolerance_cents: Number(dados.amount_tolerance_cents),
      }),
    });
    avisar("Parâmetros salvos. Concilie de novo para aplicar.");
    abrirJob(jobAtual.id);
  } catch (erro) {
    avisar(`Não deu para salvar: ${erro.message}`, true);
  }
};

$("#btn-conciliar").onclick = async () => {
  const botao = $("#btn-conciliar");
  botao.disabled = true;
  botao.textContent = "Conciliando…";
  try {
    await api(`/jobs/${jobAtual.id}/reconcile`, { method: "POST" });
    await abrirJob(jobAtual.id);
    avisar("Conciliação concluída.");
  } catch (erro) {
    avisar(erro.message, true);
    await abrirJob(jobAtual.id);
  } finally {
    botao.disabled = false;
    botao.textContent = "Conciliar";
  }
};

function desenharResumo() {
  const resumo = jobAtual.summary_json;
  $("#resumo").hidden = !resumo;
  $("#link-export").hidden = !resumo;
  if (!resumo) return;

  $("#link-export").href = `/jobs/${jobAtual.id}/export.csv`;

  const cartoes = [
    ["conciliado", resumo.conciliados, "conciliados"],
    ["divergente", resumo.divergentes, "divergentes"],
    ["pendente", resumo.pendentes, "pendentes"],
    ["taxa", `${resumo.taxa_conciliacao_automatica}%`, "conciliação automática"],
  ];

  const caixa = $("#numeros");
  caixa.textContent = "";
  for (const [classe, valor, rotulo] of cartoes) {
    const div = document.createElement("div");
    div.className = `numero ${classe}`;
    const forte = document.createElement("strong");
    forte.textContent = valor;
    const span = document.createElement("span");
    span.textContent = rotulo;
    div.append(forte, span);
    caixa.appendChild(div);
  }

  $("#resumo-frase").textContent =
    `${resumo.conciliados} conciliados | ${resumo.divergentes} divergentes | ` +
    `${resumo.pendentes} pendentes | ${resumo.taxa_conciliacao_automatica}% automático`;

  const regras = Object.entries(resumo.por_regra)
    .filter(([, quantidade]) => quantidade > 0)
    .map(([regra, quantidade]) => `${regra}: ${quantidade}`)
    .join(" · ");

  $("#resumo-rodape").textContent =
    `Regras — ${regras}. Diferença de valor acumulada: ` +
    `${brl(resumo.diferenca_de_valor_total)}. Pendentes: ` +
    `${resumo.pendentes_fonte_a} na fonte A, ${resumo.pendentes_fonte_b} na fonte B. ` +
    `Janela de ${resumo.parametros.janela_de_dias} dias, tolerância de ` +
    `${resumo.parametros.tolerancia_em_centavos} centavos.`;
}

// --- lista de resultados ---------------------------------------------------

async function carregarMatches() {
  const parametros = new URLSearchParams({ limit: "500" });
  const status = $("#filtro-status").value;
  const regra = $("#filtro-regra").value;
  if (status) parametros.set("status", status);
  if (regra) parametros.set("rule", regra);

  const matches = await api(`/jobs/${jobAtual.id}/matches?${parametros}`);
  const corpo = $("#tabela-matches tbody");
  corpo.textContent = "";

  for (const match of matches) {
    const tr = document.createElement("tr");

    const status = document.createElement("td");
    status.appendChild(etiqueta(match.status));
    tr.appendChild(status);

    tr.appendChild(celulaRegistro(match.record_a, "Venda"));
    tr.appendChild(celulaRegistro(match.record_b, "Crédito"));
    tr.appendChild(celula(match.rule === "nenhuma" ? "—" : match.rule));
    tr.appendChild(celula(match.mismatch_reason || "—"));

    const acao = document.createElement("td");
    if (match.status === "divergente") {
      const revisar = document.createElement("button");
      revisar.className = "secundario";
      revisar.textContent = "Revisar";
      revisar.onclick = () => {
        avisar(
          `Demo: revisar ${descricaoCurta(match.record_a)} x ${descricaoCurta(match.record_b)}. ` +
          "Ação visual apenas, sem persistência."
        );
      };
      acao.appendChild(revisar);
    } else {
      acao.textContent = "—";
    }
    tr.appendChild(acao);

    corpo.appendChild(tr);
  }

  $("#resultados").hidden = false;
  $("#matches-vazio").hidden = matches.length > 0;
  $("#tabela-matches").hidden = matches.length === 0;

  const link = $("#link-export");
  const filtros = parametros.toString().replace("limit=500&", "").replace("limit=500", "");
  link.href = `/jobs/${jobAtual.id}/export.csv${filtros ? "?" + filtros : ""}`;
  link.textContent = filtros ? "Exportar CSV (filtrado)" : "Exportar CSV";
}

function lado(registro) {
  if (!registro) return "—";
  const referencia = registro.reference || registro.external_id || `linha ${registro.row_number}`;
  return `${referencia} · ${dia(registro.occurred_on)} · ${brl(registro.amount)}`;
}

function descricaoCurta(registro) {
  if (!registro) return "sem par";
  return registro.reference || registro.external_id || `linha ${registro.row_number}`;
}

function celulaRegistro(registro, rotulo) {
  const td = document.createElement("td");
  td.className = "linha-registro";
  if (!registro) {
    td.textContent = "—";
    return td;
  }

  const titulo = document.createElement("strong");
  titulo.textContent = `${rotulo}: ${descricaoCurta(registro)}`;

  const valor = document.createElement("span");
  valor.textContent = `${dia(registro.occurred_on)} · ${brl(registro.amount)}`;

  const detalhes = document.createElement("span");
  detalhes.textContent =
    `ID externo: ${registro.external_id || "—"} · linha ${registro.row_number}`;

  td.append(titulo, valor, detalhes);

  if (registro.parse_error) {
    const erro = document.createElement("em");
    erro.textContent = registro.parse_error;
    td.appendChild(erro);
  }

  return td;
}

$("#filtro-status").onchange = carregarMatches;
$("#filtro-regra").onchange = carregarMatches;

// --- início ----------------------------------------------------------------

carregarJobs().catch((erro) => avisar(`API fora do ar? ${erro.message}`, true));
