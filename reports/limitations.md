# Measured limitations

- PaySim is synthetic and may contain simulator artifacts; results do not establish effectiveness at a bank or payment provider.
- The held-out test covers steps 551–743. Model, rules and policy were frozen on earlier windows; temporal prevalence drift limits transfer to other periods.
- Review costs, false-block costs, success rates and per-step capacities are hypothetical scenarios, not observed operational costs. Capacity is applied per simulator step using floor(step_rows × capacity_per_1000 / 1000); excess reviews become approvals while flags remain.
- Scores and decisions are research outputs. They do not affect real transactions; see the README disclaimer.
- The held-out fraud prevalence measured in this run was 0.010926; the strategy rows share the same test labels.
