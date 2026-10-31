"""Phase 4 dispatch configuration: cargo weights and execution constants.

SIMULATION DEMO ASSUMPTIONS — the packing weights below are illustrative
demonstration values for the simulated Thanjavur flood scenario. They are NOT
universal product weights. All values are kept in one place and can be
overridden via environment variables with the `DISPATCH_` prefix.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Kilograms per unit of each supply type (packing assumption).
CARGO_WEIGHT_KG: dict[str, float] = {
    "water_litre": 1.0,   # 1 kg per litre (water at ~1 kg/L)
    "food_kit": 2.0,      # 2 kg per food kit
    "medical_kit": 1.0,   # 1 kg per medical kit
    "hygiene_kit": 2.0,   # 2 kg per hygiene kit
}


class DispatchSettings(BaseSettings):
    """Dispatch execution settings (all overridable via env / `.env`)."""

    model_config = SettingsConfigDict(
        env_prefix="DISPATCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Minutes of simulated travel consumed per default advance call.
    advance_step_minutes: float = 60.0
    #: Minutes by which a rerouted order must differ before it is marked
    #: `delayed` (small rounding differences should not delay an order).
    delay_threshold_minutes: float = 5.0
    #: Minimum cargo weight (kg) considered worth assigning a heavy truck at
    #: all; below this smaller vehicles are preferred.
    min_cargo_weight_kg: float = 0.0

    def cargo_weight_kg(self) -> dict[str, float]:
        """Packing weight per unit (copy for outside use)."""
        return dict(CARGO_WEIGHT_KG)

    def weight_for(self, supply_type: str) -> float:
        """Weight per unit of one supply type (0.0 when unknown)."""
        return CARGO_WEIGHT_KG.get(supply_type, 0.0)


dispatch_settings = DispatchSettings()
