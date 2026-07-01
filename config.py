import toml
from schemas import ProjectConfig, PostgresConfig, IBConnectionInfo

ENV_PATH = "./env/config.toml"

with open(ENV_PATH, "r") as f:
    config = toml.load(f)


PROJECT_CONFIG = ProjectConfig(**config["project"])
POSTGRES_CONFIG = PostgresConfig(**config["database"]["postgres"])
if PROJECT_CONFIG.flag == "paper" and PROJECT_CONFIG.proxy == "gateway":
    IB_CONFIG = IBConnectionInfo(
        host=config["IB"]["host"],
        port=config["IB"]["paper_gateway_port"],
        size=config["IB"]["size"],
    )
