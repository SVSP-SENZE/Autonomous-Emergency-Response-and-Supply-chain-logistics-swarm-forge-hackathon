"""Dedicated planning configuration: ALL Phase-2 constants live here.

SIMULATION DEMO ASSUMPTIONS — the consumption rates, priority weights and risk
penalty below are illustrative demonstration values for the simulated Thanjavur
flood scenario. They are NOT official emergency standards or medical
recommendations, and must be reviewed with domain experts before any
operational use.

Every value can be overridden through environment variables with a
`PLANNING_` prefix (e.g. `PLANNING_WATER_LITRES_PER_PERSON_PER_DAY=2.5`) or in
the `.env` file, keeping them configurable without touching code.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Planning horizons accepted by the API (hours).
ALLOWED_HORIZONS: tuple[int, ...] = (6, 12, 24, 48, 72)

#: Default planning horizon (hours).
DEFAULT_HORIZON: int = 24

#: Canonical unit per supply type. Unit incompatibility is enforced during
#: allocation: the warehouse stock unit and the centre stock unit must match
#: the canonical unit for the supply type to be allocated / compared.
SUPPLY_UNIT: dict[str, str] = {
    "water_litre": "litres",
    "food_kit": "kits",
    "medical_kit": "kits",
    "hygiene_kit": "kits",
}

#: Mapping from severity/priority levels to a 0-100 "urgency" component used by
#: the demand priority score. (Documented demo calibration.)
PRIORITY_SCORE_MAP: dict[str, float] = {
    "low": 25.0,
    "medium": 50.0,
    "high": 75.0,
    "critical": 90.0,
}

#: Priority classification thresholds on the composite 0-100 score.
PRIORITY_CLASSIFICATION_THRESHOLDS: dict[str, float] = {
    "critical": 85.0,
    "high": 65.0,
    "medium": 40.0,
    # below 40 -> "low"
}


class PlanningSettings(BaseSettings):
    """Planning engine settings (consumption rates, weights, penalties)."""

    model_config = SettingsConfigDict(
        env_prefix="PLANNING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Consumption rates (per person per day) — DEMO ASSUMPTIONS ------------
    water_litres_per_person_per_day: float = 3.0
    food_kits_per_person_per_day: float = 0.2          # 1 kit per 5 people/day
    medical_kits_per_person_per_day: float = 0.02      # 1 kit per 50 people/day
    hygiene_kits_per_person_per_day: float = 0.1       # 1 kit per 10 people/day

    # --- Routing / route cost ------------------------------------------------
    #: Minutes added to a route per unit of normalised risk (0-1 scale).
    risk_penalty_minutes: float = 120.0

    # --- Demand priority score weights (should total ~= 1.0) -----------------
    priority_component_weight: float = 0.40  # existing centre priority
    shortage_component_weight: float = 0.35  # shortage severity
    population_component_weight: float = 0.15  # affected population
    supply_risk_component_weight: float = 0.10  # current stock availability

    @property
    def consumption_rates(self) -> dict[str, float]:
        """Daily consumption rate per person for each supply type."""
        return {
            "water_litre": self.water_litres_per_person_per_day,
            "food_kit": self.food_kits_per_person_per_day,
            "medical_kit": self.medical_kits_per_person_per_day,
            "hygiene_kit": self.hygiene_kits_per_person_per_day,
        }

    def validate_weights(self) -> None:
        """Guard against misconfigured weight sums (log-friendly, deterministic)."""
        total = (
            self.priority_component_weight
            + self.shortage_component_weight
            + self.population_component_weight
            + self.supply_risk_component_weight
        )
        if abs(total - 1.0) > 1e-6:  # pragma: no cover - configuration guard
            raise ValueError(
                "Demand priority weights must sum to 1.0 "
                f"(current sum: {total:.6f})"
            )


planning_settings = PlanningSettings()
