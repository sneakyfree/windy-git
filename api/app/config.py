"""Settings for the windy-git plane.

Every `env:` default in DNA_STRAND_MASTER_PLAN.md is shipped here as an actual
default, not a suggestion. Providers are FAIL-CLOSED (I-8): a provider whose
credentials are absent reports itself unconfigured and refuses to answer, rather
than answering from a mock. The domains cell shipped a portal on a mock registrar
and told the public that google.com was available for $18.00 a year. That failure
mode is banned here by construction.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- service identity -------------------------------------------------
    environment: str = "development"
    service_name: str = "windy-git"
    port: int = 8600

    # ---- database ---------------------------------------------------------
    # Postgres schema `windgit`, own alembic (G0.4).
    database_url: str = "postgresql+asyncpg://windygit:windygit@localhost:5432/windygit"
    db_schema: str = "windgit"

    # ---- Gitea (a COMPONENT behind an API membrane, never a merged tree) ---
    gitea_base_url: str = "http://localhost:3000"
    gitea_admin_token: str = ""

    # ---- Cloudflare R2 (I-3: heavy bytes only, never git objects) ---------
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_lfs: str = "windy-git-lfs"
    r2_bucket_artifacts: str = "windy-git-artifacts"
    r2_bucket_backups: str = "windy-git-backups"

    # ---- Eternitas (agent identity + trust) -------------------------------
    eternitas_base_url: str = "https://api.eternitas.ai"
    eternitas_platform_api_key: str = ""
    # Signs webhooks Eternitas delivers to us. Unset = we refuse them (I-8):
    # accepting unverified instructions about identity is worse than missing them.
    eternitas_webhook_secret: str = ""
    eternitas_platform_id: str = ""

    # ---- account-server OIDC (human identity) -----------------------------
    account_server_base_url: str = "https://account.windyword.ai"

    # Internal callers (the Cloud portal calling /internal/*). A first-class
    # caller class, not a bypass: unset means service calls are REFUSED.
    service_token: str = ""

    # ⚠️ FAIL-CLOSED GATE. Full RS256/ES256 JWKS verification lands in G3.2.
    # Until it does, the human token path must not be reachable in production —
    # accepting an unverified JWT is not a shortcut, it is an authentication
    # bypass. Agents are unaffected: their authority comes from a live Eternitas
    # trust lookup, not from anything the token asserts about itself.
    require_verified_jwt: bool = True

    # ---- storage law (I-3, G4.4) ------------------------------------------
    # Git object databases MUST live on a POSIX filesystem. A test asserts this
    # path does not resolve to a network mount.
    git_data_root: str = "/srv/windygit/git"

    # ---- LFS threshold (G4.5) ---------------------------------------------
    # Small text files stay in git proper. LFS-for-everything makes clones slow
    # and operations heavy.
    lfs_threshold_bytes: int = 5 * 1024 * 1024  # env: 5 MB
    lfs_extensions: tuple[str, ...] = (
        ".safetensors", ".bin", ".gguf", ".pt", ".ckpt", ".onnx",
        ".zip", ".tar", ".gz", ".mp4", ".wav", ".mov", ".psd",
    )

    # ---- velocity bases, multiplied by EI band (G3.4) ---------------------
    # Platinum x10 / Gold x4 / Standard x1 / Watch x0.5 / Untrusted read-only
    rate_pushes_per_day: int = 500
    rate_repo_creates_per_day: int = 50
    rate_grants_per_day: int = 100
    rate_force_pushes_per_day: int = 10

    # ---- mirror: I-4, never a one-way door --------------------------------
    github_token: str = ""
    github_owner: str = "sneakyfree"
    # Gitea's timer, as a backstop. sync_on_commit is what actually matters:
    # an hourly window means an hour of work can be the thing you lose.
    mirror_interval: str = "8h0m0s"
    mirror_lag_p2_seconds: int = 3600  # env: 60 min -> P2

    # ---- agent grants (G5.3) ----------------------------------------------
    agent_grant_default_days: int = 90

    # ---- repo types (I-7: first-class from migration 001) -----------------
    repo_types_enabled: tuple[str, ...] = ("code",)  # model/dataset are v2

    # ---- feature gates ----------------------------------------------------
    # Mirrors the sibling `edge_live` pattern (windy-cloud-sites, a8ff948):
    # never claim live while a provider is mock.
    hf_compat_enabled: bool = False  # Grant-gated, DNA plan section 7.7

    kit0_host: str = Field(
        default="72.60.118.54",
        description="Recorded ONLY so the G1 guard can refuse to deploy here (D-4).",
    )

    # ---- derived ----------------------------------------------------------
    @property
    def r2_configured(self) -> bool:
        return bool(
            self.r2_account_id and self.r2_access_key_id and self.r2_secret_access_key
        )

    @property
    def gitea_configured(self) -> bool:
        return bool(self.gitea_base_url and self.gitea_admin_token)

    @property
    def eternitas_configured(self) -> bool:
        return bool(self.eternitas_base_url and self.eternitas_platform_api_key)

    @property
    def r2_endpoint_url(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
