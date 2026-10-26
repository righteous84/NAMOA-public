# Explicit decision-rule fusion weights.
#
# Policy:
#
# - Every rule wired into the DecisionEngine MUST have an explicit
#   entry here. There is no implicit default weight: FusionEngine
#   refuses to fuse a signal whose rule has no configured weight, so
#   an unconfigured active rule fails clearly instead of silently
#   inheriting undocumented policy.
#
# - Values are relative importance priors used only when MULTIPLE
#   signals fuse; a lone signal's fused outcome is independent of its
#   weight (the factor cancels).
#
# - hdr_rule, source_rule and other preservation/constraint rules
#   rarely emit opportunity signals; their weights remain declared so
#   the inventory is complete and explicit.
#
# - audio_rule was introduced with the intelligence relationship work
#   and participates at the same relative importance as resolution.
#
# Weight changes are intelligence-affecting and participate in the
# run-level policy snapshot and intelligence identity.

RULE_WEIGHTS = {
    "codec_rule": 1.0,
    "bitrate_rule": 0.8,
    "hdr_rule": 0.7,
    "resolution_rule": 0.6,
    "container_rule": 0.5,
    "source_rule": 0.5,
    "audio_rule": 0.6,
}