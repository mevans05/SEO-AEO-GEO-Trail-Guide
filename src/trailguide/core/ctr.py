"""Position-to-CTR modeling with SERP-feature suppression.

Two jobs, both central to the SEO measurement POV:

1. Estimate the clicks a keyword *would* earn at a target position, which turns
   a ranking change into a traffic change and then into revenue.
2. Estimate the clicks the SERP *withholds* - the zero-click gap between the
   CTR a position should earn and the CTR it actually earns. That gap is the
   raw material for the Track 2 dark-organic estimate.

Curves are defaults grounded in published CTR studies and are meant to be
overridden per client in config once first-party data justifies it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .coerce import clamp

#: Blended non-branded organic CTR by integer position.
DEFAULT_NONBRANDED_CURVE: dict[int, float] = {
    1: 0.281, 2: 0.157, 3: 0.110, 4: 0.080, 5: 0.061,
    6: 0.048, 7: 0.040, 8: 0.033, 9: 0.028, 10: 0.025,
    11: 0.019, 12: 0.016, 13: 0.014, 14: 0.013, 15: 0.012,
    16: 0.011, 17: 0.010, 18: 0.009, 19: 0.008, 20: 0.007,
}

#: Branded queries earn far higher CTR at the same position.
DEFAULT_BRANDED_CURVE: dict[int, float] = {
    1: 0.452, 2: 0.208, 3: 0.131, 4: 0.091, 5: 0.067,
    6: 0.052, 7: 0.043, 8: 0.036, 9: 0.030, 10: 0.027,
    11: 0.020, 12: 0.017, 13: 0.015, 14: 0.013, 15: 0.012,
    16: 0.011, 17: 0.010, 18: 0.009, 19: 0.008, 20: 0.007,
}

#: Multiplicative CTR effect of SERP features being present on the result page.
#: Values below 1.0 suppress clicks (the answer is satisfied on the SERP);
#: values above 1.0 reflect features the brand owns and benefits from.
DEFAULT_FEATURE_EFFECTS: dict[str, float] = {
    "ai_overview": 0.60,
    "ai_overview_cited": 0.78,      # suppressed, but the brand is inside the answer
    "featured_snippet": 0.75,
    "featured_snippet_owned": 1.32,
    "people_also_ask": 0.92,
    "knowledge_panel": 0.85,
    "local_pack": 0.80,
    "shopping": 0.85,
    "video_carousel": 0.88,
    "image_pack": 0.93,
    "top_ads": 0.88,
    "sitelinks": 1.05,
    "review_snippet": 1.08,
}

#: Floor on the combined feature multiplier; stacked features never zero out clicks.
MIN_FEATURE_MULTIPLIER = 0.25


@dataclass
class CTRModel:
    """CTR curves plus SERP-feature effects, all configurable per client."""

    nonbranded: dict[int, float] = field(default_factory=lambda: dict(DEFAULT_NONBRANDED_CURVE))
    branded: dict[int, float] = field(default_factory=lambda: dict(DEFAULT_BRANDED_CURVE))
    feature_effects: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_FEATURE_EFFECTS))
    tail_ctr: float = 0.004
    max_modeled_position: int = 20

    @classmethod
    def from_config(cls, config: dict | None) -> "CTRModel":
        """Build a model from a config mapping, falling back to defaults."""
        config = config or {}
        model = cls()
        for key, target in (("nonbranded", model.nonbranded), ("branded", model.branded)):
            overrides = config.get(key) or {}
            for position, value in overrides.items():
                target[int(position)] = float(value)
        model.feature_effects.update(config.get("feature_effects") or {})
        if "tail_ctr" in config:
            model.tail_ctr = float(config["tail_ctr"])
        if "max_modeled_position" in config:
            model.max_modeled_position = int(config["max_modeled_position"])
        return model

    def base_ctr(self, position: float | None, branded: bool = False) -> float:
        """Expected CTR at ``position`` with no SERP-feature adjustment.

        Fractional positions (Search Console reports averages) are linearly
        interpolated between the two bracketing integer positions.
        """
        if position is None or position <= 0:
            return 0.0
        curve = self.branded if branded else self.nonbranded
        if position >= self.max_modeled_position:
            return self.tail_ctr
        low = int(position)
        high = low + 1
        low_ctr = curve.get(low, self.tail_ctr)
        high_ctr = curve.get(high, self.tail_ctr)
        fraction = position - low
        return low_ctr + (high_ctr - low_ctr) * fraction

    def feature_multiplier(self, serp_features: list[str] | None) -> float:
        """Combined multiplicative effect of the SERP features present.

        Effects compound, then clamp at :data:`MIN_FEATURE_MULTIPLIER` so an
        unusually feature-heavy SERP cannot model away every click.
        """
        if not serp_features:
            return 1.0
        multiplier = 1.0
        for feature in serp_features:
            key = str(feature).strip().lower().replace(" ", "_").replace("-", "_")
            multiplier *= self.feature_effects.get(key, 1.0)
        return max(MIN_FEATURE_MULTIPLIER, multiplier)

    def expected_ctr(
        self,
        position: float | None,
        branded: bool = False,
        serp_features: list[str] | None = None,
    ) -> float:
        """Expected CTR at a position on this specific SERP."""
        return self.base_ctr(position, branded) * self.feature_multiplier(serp_features)

    def click_delta(
        self,
        impressions: float,
        current_position: float | None,
        target_position: float,
        branded: bool = False,
        serp_features: list[str] | None = None,
    ) -> float:
        """Incremental clicks from moving ``current_position`` to ``target_position``.

        Never negative: an opportunity is only counted when the target position
        is genuinely better than the current one.
        """
        if impressions <= 0 or current_position is None:
            return 0.0
        if target_position >= current_position:
            return 0.0
        current = self.expected_ctr(current_position, branded, serp_features)
        target = self.expected_ctr(target_position, branded, serp_features)
        return max(0.0, impressions * (target - current))

    def suppressed_clicks(
        self,
        impressions: float,
        position: float | None,
        observed_clicks: float,
        branded: bool = False,
        serp_features: list[str] | None = None,
    ) -> float:
        """Clicks the SERP withheld relative to an unobstructed curve.

        The gap between the CTR the position would earn on a plain SERP and the
        CTR actually observed. This is the zero-click signal feeding Track 2:
        the demand existed and the brand was visible, but the click never came.
        """
        if impressions <= 0 or position is None:
            return 0.0
        unobstructed = self.base_ctr(position, branded) * impressions
        return max(0.0, unobstructed - max(0.0, observed_clicks))

    def zero_click_rate(self, serp_features: list[str] | None) -> float:
        """Share of impressions this SERP's features are expected to absorb."""
        return clamp(1.0 - self.feature_multiplier(serp_features), 0.0, 0.85)
