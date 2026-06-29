import toml
from schemas.config import PostgresConfig, SymbolConfig

ENV_PATH = "./env/config.toml"

with open(ENV_PATH, "r") as f:
    config = toml.load(f)


POSTGRES_CONFIG = PostgresConfig(**config["database"]["postgres"])
SYMBOL_CONFIG = SymbolConfig(**config["symbol"])
