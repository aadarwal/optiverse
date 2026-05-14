# Critic Prompt

Use this after a deterministic evaluator report exists.

Recommended prompt contents:

- benchmark goal
- planner output
- validation report
- trace/scoring report
- generated ray-path summaries

Ask the model to explain the likely failure and suggest a revised plan. Keep this separate from deterministic scoring: the critic can propose edits, but the raytracer and scorer remain the source of truth.
