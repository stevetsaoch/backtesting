import toml
from schemas import (
    ProjectConfig,
    PostgresConfig,
    IBConnectionPoolInfo,
    SymbolInfo,
    NautilusConfig,
    VenueConfig,
)

ENV_PATH = "./env/config.toml"

with open(ENV_PATH, "r") as f:
    config = toml.load(f)


PROJECT_CONFIG = ProjectConfig(**config["project"])
POSTGRES_CONFIG = PostgresConfig(**config["database"]["postgres"])
if PROJECT_CONFIG.flag == "paper" and PROJECT_CONFIG.proxy == "gateway":
    IB_CONFIG = IBConnectionPoolInfo(
        host=config["IB"]["host"],
        port=config["IB"]["paper_gateway_port"],
        size=config["IB"]["size"],
    )
if PROJECT_CONFIG.flag == "paper" and PROJECT_CONFIG.proxy == "tws":
    IB_CONFIG = IBConnectionPoolInfo(
        host=config["IB"]["host"],
        port=config["IB"]["paper_tws_port"],
        size=config["IB"]["size"],
    )
SYMBOL_CONFIG = SymbolInfo(**config["symbol"])
NAUTILUS_CONFIG = NautilusConfig(**config["nautilus"])
VENUE_CONFIG = VenueConfig(**config["venue"])
