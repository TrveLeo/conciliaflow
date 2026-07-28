from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://conciliaflow:conciliaflow@localhost:5433/conciliaflow"

    # Diretório onde os arquivos enviados ficam guardados.
    upload_dir: str = "./uploads"

    # Limite por arquivo. Planilha de PME raramente passa disso; acima é sinal
    # de que o caso pede integração direta, não upload manual.
    max_upload_mb: int = 20

    # Parâmetros padrão da conciliação (sobrescrevíveis por job).
    date_window_days: int = 3
    amount_tolerance_cents: int = 5

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
