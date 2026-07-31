// Frontend do ConciliaFlow: uma página, sem build step.
// Consome a mesma API pública documentada em /docs — nada de rota especial
// para a tela.

const $ = (sel) => document.querySelector(sel);

const FONTES = [
  ["a", "Fonte A — sistema interno", true],
  ["b", "Fonte B — extrato", true],
  ["c", "Fonte C — opcional", false],
];

// Glifo por status. Junto com a palavra, garante que a informação sobreviva
// sem cor — daltonismo, impressão em preto e branco, alto contraste forçado.
const GLIFO = {
  conciliado: "✓",
  divergente: "!",
  pendente: "•",
  concluido: "✓",
  erro: "!",
  conciliando: "•",
  importando: "•",
  criado: "•",
  pronto: "•",
};

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
  caixa.classList.toggle("toast--error", falhou);
  caixa.hidden = false;
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => { caixa.hidden = true; }, falhou ? 8000 : 3500);
}

const brl = (valor) =>
  valor === null || valor === undefined
    ? "—"
    : Number(valor).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const dia = (iso) => (iso ? iso.split("-").reverse().join("/") : "—");
const textoOuTraco = (v) => (v === null || v === undefined || v === "" ? "—" : String(v));

function celula(texto, classe) {
  const td = document.createElement("td");
  td.textContent = texto;
  if (classe) td.className = classe;
  return td;
}

/** Selo de status: cor + glifo + palavra, sempre os três juntos. */
function selo(status) {
  const span = document.createElement("span");
  span.className = `badge badge--${status}`;
  const icone = document.createElement("span");
  icone.className = "badge__icon";
  icone.setAttribute("aria-hidden", "true");
  icone.textContent = GLIFO[status] || "•";
  span.append(icone, document.createTextNode(status));
  return span;
}

function marcaRegra(regra) {
  const span = document.createElement("span");
  if (regra === "nenhuma" || !regra) {
    span.className = "rule rule--none";
    span.textContent = "sem regra";
  } else {
    span.className = "rule";
    span.textContent = regra;
  }
  return span;
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
    const link = document.createElement("button");
    link.type = "button";
    link.className = "link";
    link.textContent = job.name;
    link.onclick = () => abrirJob(job.id);
    nome.appendChild(link);
    tr.appendChild(nome);

    const status = document.createElement("td");
    status.appendChild(selo(job.status));
    tr.appendChild(status);

    tr.appendChild(celula(new Date(job.created_at).toLocaleString("pt-BR")));

    const acao = document.createElement("td");
    const apagar = document.createElement("button");
    apagar.type = "button";
    apagar.className = "button button--small button--danger";
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
  status.textContent = "";
  status.appendChild(selo(jobAtual.status));

  $("#form-parametros [name=date_window_days]").value = jobAtual.date_window_days;
  $("#form-parametros [name=amount_tolerance_cents]").value = jobAtual.amount_tolerance_cents;

  desenharFontes();
  desenharResumo();

  if (jobAtual.summary_json) {
    $("#bloco-analise").hidden = false;
    desenharGraficoRegras();
    carregarMatches();
  } else {
    $("#bloco-analise").hidden = true;
  }
}

function desenharFontes() {
  const caixa = $("#fontes");
  caixa.textContent = "";
  const porFonte = Object.fromEntries((jobAtual.sources || []).map((s) => [s.source, s]));

  for (const [lado, titulo, obrigatoria] of FONTES) {
    const info = porFonte[lado];
    const div = document.createElement("div");
    div.className = "source";
    if (info && info.filename) div.classList.add("source--filled");
    if (info && info.rows_with_error > 0) div.classList.add("source--error");

    const h4 = document.createElement("p");
    h4.className = "source__title";
    h4.textContent = titulo;
    div.appendChild(h4);

    if (!obrigatoria) {
      const dica = document.createElement("span");
      dica.className = "source__hint";
      dica.textContent = "não entra na conciliação";
      div.appendChild(dica);
    }

    const stat = document.createElement("p");
    stat.className = "source__stat";
    if (info && info.filename) {
      stat.textContent =
        `${info.filename} — ${info.rows} linhas, ${info.rows_with_error} com erro, ${brl(info.total_amount)}`;
      if (info.rows_with_error > 0) stat.classList.add("source__stat--error");
    } else {
      stat.textContent = "nenhum arquivo enviado";
    }
    div.appendChild(stat);

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

// --- resumo ----------------------------------------------------------------

function desenharResumo() {
  const resumo = jobAtual.summary_json;
  $("#resumo").hidden = !resumo;
  $("#link-export").hidden = !resumo;
  if (!resumo) return;

  $("#link-export").href = `/jobs/${jobAtual.id}/export.csv`;

  const cartoes = [
    ["Conciliados", resumo.conciliados, "fecharam sozinhos", "good"],
    ["Divergentes", resumo.divergentes, "casaram com diferença", "critical"],
    ["Pendentes", resumo.pendentes, `${resumo.pendentes_fonte_a} em A · ${resumo.pendentes_fonte_b} em B`, "warning"],
    ["Automático", `${resumo.taxa_conciliacao_automatica}%`, "sem intervenção", null],
    ["Diferença acumulada", brl(resumo.diferenca_de_valor_total), "soma das divergências", null],
  ];

  const caixa = $("#numeros");
  caixa.textContent = "";
  for (const [rotulo, valor, nota, tom] of cartoes) {
    const div = document.createElement("div");
    div.className = "kpi" + (tom ? ` kpi--${tom}` : "");
    const label = document.createElement("span");
    label.className = "kpi__label";
    label.textContent = rotulo;
    const forte = document.createElement("strong");
    forte.className = "kpi__value";
    forte.textContent = valor;
    const span = document.createElement("span");
    span.className = "kpi__note";
    span.textContent = nota;
    div.append(label, forte, span);
    caixa.appendChild(div);
  }

  $("#resumo-rodape").textContent =
    `Janela de ${resumo.parametros.janela_de_dias} dias, tolerância de ` +
    `${resumo.parametros.tolerancia_em_centavos} centavos. ` +
    `${resumo.total_resultados} pares avaliados.`;
}

// --- gráfico de regras -----------------------------------------------------

const NS = "http://www.w3.org/2000/svg";

function svgEl(nome, attrs = {}) {
  const node = document.createElementNS(NS, nome);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  return node;
}

/** Escala com passo inteiro da família 1, 2, 5 × 10^n. */
function escala(valor, marcas = 4) {
  const seguro = Math.max(1, valor);
  const bruto = seguro / marcas;
  const base = 10 ** Math.floor(Math.log10(bruto));
  const n = bruto / base;
  const passo = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * base;
  const max = Math.ceil(seguro / passo) * passo;
  const ticks = [];
  for (let t = 0; t <= max + 1e-9; t += passo) ticks.push(Math.round(t));
  return { max, ticks };
}

function barra(x, y, largura, altura, raio) {
  const r = Math.max(0, Math.min(raio, largura));
  return `M${x},${y} H${x + largura - r} Q${x + largura},${y} ${x + largura},${y + r} V${y + altura - r} Q${x + largura},${y + altura} ${x + largura - r},${y + altura} H${x} Z`;
}

function desenharGraficoRegras() {
  const host = $("#grafico-regras");
  const porRegra = jobAtual.summary_json.por_regra || {};
  const dados = Object.entries(porRegra)
    .filter(([, n]) => n > 0)
    .map(([regra, n]) => ({ rotulo: regra === "nenhuma" ? "sem regra" : regra, valor: n }));

  if (!dados.length) {
    host.innerHTML = `<p class="empty">Nada conciliado ainda.</p>`;
    return;
  }

  const larguraRotulo = 118;
  const alturaLinha = 28;
  const gap = 8;
  const padDireita = 40;
  const largura = host.clientWidth || 340;
  const altura = dados.length * alturaLinha + (dados.length - 1) * gap + 24;
  const larguraPlot = Math.max(40, largura - larguraRotulo - padDireita);
  const { max, ticks } = escala(Math.max(...dados.map((d) => d.valor)));

  const svg = svgEl("svg", {
    class: "chart",
    viewBox: `0 0 ${largura} ${altura}`,
    role: "img",
    "aria-label": `Pares por regra. ${dados.map((d) => `${d.rotulo}: ${d.valor}`).join(". ")}.`,
  });

  ticks.forEach((tick) => {
    const x = larguraRotulo + (tick / max) * larguraPlot;
    svg.append(
      svgEl("line", { class: "chart__grid", x1: x, y1: 0, x2: x, y2: altura - 22 }),
      Object.assign(svgEl("text", { x, y: altura - 6, "text-anchor": "middle" }), {
        textContent: tick,
      }),
    );
  });

  dados.forEach((linha, i) => {
    const y = i * (alturaLinha + gap);
    const larguraBarra = Math.max(2, (linha.valor / max) * larguraPlot);

    svg.append(
      Object.assign(
        svgEl("text", { x: larguraRotulo - 10, y: y + alturaLinha / 2 + 4, "text-anchor": "end" }),
        { textContent: linha.rotulo },
      ),
    );

    const marca = svgEl("path", {
      class: "chart__mark",
      d: barra(larguraRotulo, y, larguraBarra, alturaLinha, 4),
      fill: "var(--s1)",
    });
    svg.append(marca);

    svg.append(
      Object.assign(
        svgEl("text", {
          class: "chart__value",
          x: larguraRotulo + larguraBarra + 8,
          y: y + alturaLinha / 2 + 4,
        }),
        { textContent: linha.valor },
      ),
    );

    const alvo = svgEl("rect", {
      class: "chart__hit",
      x: larguraRotulo,
      y: y - gap / 2,
      width: larguraPlot + padDireita,
      height: alturaLinha + gap,
    });
    svg.append(alvo);

    alvo.addEventListener("mouseenter", (e) => {
      marca.classList.add("chart__mark--active");
      mostrarTooltip(e, linha.rotulo, [["Pares", linha.valor]]);
    });
    alvo.addEventListener("mousemove", moverTooltip);
    alvo.addEventListener("mouseleave", () => {
      marca.classList.remove("chart__mark--active");
      esconderTooltip();
    });
  });

  host.replaceChildren(svg);
}

function mostrarTooltip(evento, titulo, linhas) {
  const t = $("#tooltip");
  t.innerHTML =
    `<div class="tooltip__title"></div>` +
    linhas.map(() => `<div class="tooltip__row"><span></span><span></span></div>`).join("");
  t.querySelector(".tooltip__title").textContent = titulo;
  t.querySelectorAll(".tooltip__row").forEach((row, i) => {
    row.children[0].textContent = linhas[i][0];
    row.children[1].textContent = linhas[i][1];
  });
  t.dataset.visible = "true";
  moverTooltip(evento);
}

function moverTooltip(evento) {
  const t = $("#tooltip");
  const r = t.getBoundingClientRect();
  let x = evento.clientX + 14;
  let y = evento.clientY + 14;
  if (x + r.width > window.innerWidth - 8) x = evento.clientX - r.width - 14;
  if (y + r.height > window.innerHeight - 8) y = evento.clientY - r.height - 14;
  t.style.left = `${Math.max(8, x)}px`;
  t.style.top = `${Math.max(8, y)}px`;
}

function esconderTooltip() {
  $("#tooltip").dataset.visible = "false";
}

// --- fila de exceções ------------------------------------------------------

/**
 * Busca os pares da lista.
 *
 * O filtro padrão é "exceções", não "todos". Numa conciliação de 200 linhas,
 * abrir na lista completa esconde as 30 que precisam de decisão humana no meio
 * das que fecharam sozinhas. A API filtra por um status só, então exceções
 * viram duas chamadas.
 */
async function buscarMatches(status, regra) {
  const monta = (st) => {
    const p = new URLSearchParams({ limit: "500" });
    if (st) p.set("status", st);
    if (regra) p.set("rule", regra);
    return `/jobs/${jobAtual.id}/matches?${p}`;
  };

  if (status !== "excecoes") return api(monta(status));

  const [divergentes, pendentes] = await Promise.all([
    api(monta("divergente")),
    api(monta("pendente")),
  ]);
  return [...divergentes, ...pendentes];
}

async function carregarMatches() {
  const status = $("#filtro-status").value;
  const regra = $("#filtro-regra").value;
  const matches = await buscarMatches(status, regra);

  const corpo = $("#tabela-matches tbody");
  corpo.textContent = "";

  for (const match of matches) {
    const tr = document.createElement("tr");

    const tdStatus = document.createElement("td");
    tdStatus.appendChild(selo(match.status));
    tr.appendChild(tdStatus);

    tr.appendChild(celulaRegistro(match.record_a));
    tr.appendChild(celulaRegistro(match.record_b));

    const tdRegra = document.createElement("td");
    tdRegra.appendChild(marcaRegra(match.rule));
    tr.appendChild(tdRegra);

    tr.appendChild(celula(match.mismatch_reason || "—"));

    const acao = document.createElement("td");
    const abrir = document.createElement("button");
    abrir.type = "button";
    abrir.className = "button button--small";
    abrir.textContent = "Comparar";
    abrir.onclick = () => abrirInspecao(match);
    acao.appendChild(abrir);
    tr.appendChild(acao);

    corpo.appendChild(tr);
  }

  $("#matches-vazio").hidden = matches.length > 0;
  $("#tabela-matches").hidden = matches.length === 0;
  $("#matches-contagem").textContent =
    `${matches.length} ${matches.length === 1 ? "par" : "pares"} neste filtro`;

  // O export acompanha o filtro, menos no modo exceções: a API exporta um
  // status por vez, e um CSV com metade do que está na tela seria pior que
  // um CSV completo.
  const link = $("#link-export");
  const p = new URLSearchParams();
  if (status && status !== "excecoes") p.set("status", status);
  if (regra) p.set("rule", regra);
  const query = p.toString();
  link.href = `/jobs/${jobAtual.id}/export.csv${query ? "?" + query : ""}`;
  link.textContent = query ? "Exportar CSV (filtrado)" : "Exportar CSV";
}

function descricaoCurta(registro) {
  return registro.reference || registro.external_id || `linha ${registro.row_number}`;
}

function celulaRegistro(registro) {
  const td = document.createElement("td");
  if (!registro) {
    td.className = "rec--empty";
    td.textContent = "— sem par";
    return td;
  }

  const wrap = document.createElement("div");
  wrap.className = "rec";

  const ref = document.createElement("span");
  ref.className = "rec__ref";
  ref.textContent = descricaoCurta(registro);

  const linha = document.createElement("span");
  linha.className = "rec__line";
  linha.textContent = `${dia(registro.occurred_on)} · ${brl(registro.amount)}`;

  const meta = document.createElement("span");
  meta.className = "rec__meta";
  meta.textContent = `id ${registro.external_id || "—"} · linha ${registro.row_number}`;

  wrap.append(ref, linha, meta);

  if (registro.parse_error) {
    const erro = document.createElement("span");
    erro.className = "rec__error";
    erro.textContent = registro.parse_error;
    wrap.appendChild(erro);
  }

  td.appendChild(wrap);
  return td;
}

// --- comparação lado a lado ------------------------------------------------

function abrirInspecao(match) {
  $("#inspecao-overlay").hidden = false;
  $("#painel-inspecao").hidden = false;

  const status = $("#inspecao-status");
  status.textContent = "";
  status.appendChild(selo(match.status));

  const regra = $("#inspecao-regra");
  regra.className = match.rule === "nenhuma" ? "rule rule--none" : "rule";
  regra.textContent = match.rule === "nenhuma" ? "sem regra" : match.rule;

  const motivo = $("#inspecao-motivo");
  motivo.textContent = match.mismatch_reason || "Par sem divergência registrada.";
  motivo.hidden = false;

  const metricas = $("#inspecao-metricas");
  metricas.textContent = "";
  const cards = [
    ["Diferença de valor", brl(match.amount_difference)],
    ["Diferença de dias", match.days_difference === null ? "—" : `${match.days_difference} dia(s)`],
  ];
  for (const [rotulo, valor] of cards) {
    const div = document.createElement("div");
    div.className = "metric";
    const forte = document.createElement("strong");
    forte.textContent = valor;
    const span = document.createElement("span");
    span.textContent = rotulo;
    div.append(forte, span);
    metricas.appendChild(div);
  }

  // Campos que diferem entre os dois lados são marcados nos DOIS, para que a
  // comparação não dependa de o olho ir e voltar procurando o que mudou.
  const difere = camposDivergentes(match.record_a, match.record_b);
  preencherLado("#inspecao-venda", match.record_a, "venda", difere);
  preencherLado("#inspecao-credito", match.record_b, "crédito", difere);
}

function camposDivergentes(a, b) {
  if (!a || !b) return new Set();
  const conjunto = new Set();
  if (a.occurred_on !== b.occurred_on) conjunto.add("Data");
  if (Number(a.amount) !== Number(b.amount)) conjunto.add("Valor");
  if ((a.reference || "") !== (b.reference || "")) conjunto.add("Referência");
  return conjunto;
}

function fecharInspecao() {
  $("#inspecao-overlay").hidden = true;
  $("#painel-inspecao").hidden = true;
}

function preencherLado(seletor, registro, tipo, difere) {
  const caixa = $(seletor);
  caixa.textContent = "";

  if (!registro) {
    const vazio = document.createElement("p");
    vazio.className = "empty";
    vazio.textContent = `Sem ${tipo} correspondente — este é o lado órfão do par.`;
    caixa.appendChild(vazio);
    return;
  }

  const lista = document.createElement("dl");
  lista.className = "fields";
  const campos = [
    ["Referência", registro.reference],
    ["ID externo", registro.external_id],
    ["Linha importada", registro.row_number],
    ["Data", dia(registro.occurred_on)],
    ["Valor", brl(registro.amount)],
    ["Descrição", registro.description],
    ["Erro de leitura", registro.parse_error],
  ];

  for (const [rotulo, valor] of campos) {
    const grupo = document.createElement("div");
    grupo.className = "field-row" + (difere.has(rotulo) ? " field-row--diff" : "");
    const dt = document.createElement("dt");
    dt.textContent = rotulo;
    const dd = document.createElement("dd");
    dd.textContent = textoOuTraco(valor);
    grupo.append(dt, dd);
    lista.appendChild(grupo);
  }
  caixa.appendChild(lista);

  const payload = document.createElement("pre");
  payload.className = "raw";
  payload.textContent = JSON.stringify(registro.raw_payload, null, 2);
  caixa.appendChild(payload);
}

// --- ligações --------------------------------------------------------------

$("#filtro-status").onchange = carregarMatches;
$("#filtro-regra").onchange = carregarMatches;
$("#btn-fechar-inspecao").onclick = fecharInspecao;
$("#inspecao-overlay").onclick = fecharInspecao;
document.addEventListener("keydown", (evento) => {
  if (evento.key === "Escape" && !$("#painel-inspecao").hidden) fecharInspecao();
});
window.addEventListener("resize", () => {
  if (jobAtual && jobAtual.summary_json) desenharGraficoRegras();
});

// --- início ----------------------------------------------------------------

carregarJobs().catch((erro) => avisar(`API fora do ar? ${erro.message}`, true));
