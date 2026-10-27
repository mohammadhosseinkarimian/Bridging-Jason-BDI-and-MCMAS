# Jason agent programs

This directory contains the AgentSpeak programs that supply the beliefs, goals, and plan choices used by the translator. These `.asl` files describe how an agent decides what to do. They do not contain the complete MCMAS state space or the physical effects of actions. Those are defined in the ISPL baseline models under `examples/`.

The translation reads the programs as source text. It selects the goal structure and mapped plans specified in each example's `jason_mapping.json`. We do not run a Jason interpreter during translation, and we do not try to reproduce its full event scheduling or belief revision semantics.

## `fire_brigade.asl`

This is the FireBrigade policy for the rescue experiments. The derived predicates at the beginning describe the information used by its plans. For example, `at_area(Pos)` checks the agent's location, `alive(Civ)` checks the civilian's health, and `buried_civilian(Civ,Pos,Level)` identifies a living buried civilian. `ready_for_ambulance` describes a rescued civilian who still needs transport.

A `+step(T)` event starts `!saved_civilians`. That goal is the main decision loop. It first handles a known buried civilian, a report from another agent, or a civilian ready for transport. When the civilian has been found and the FireBrigade reaches the right location, `!rescued_buried_civilian(Civ)` calls `rescue(Civ)`. After the rescue, `!told_ambulance(Civ)` uses `notify_ambulance_ready` to inform the AmbulanceTeam. This is a concrete communication action, not merely a comment in the plan.

The remaining plans support searching. `!patrol` prefers known rescue tasks, then unvisited collapsed or damaged buildings, other buildings, and roads. `!visited(Pos)` moves to an area and records that it has been visited. These plans matter in the relation-aware rescue examples because we use their ordering to classify locations and keep equally ranked movement choices. The fallback is `rest`, rather than forcing a movement in every state.

The plans also include belief additions such as `+found_civilian` and `+visited`, test goals such as `?saved_civilians`, and failure handlers beginning with `-!`. Not all of these become MCMAS transitions. The mapping determines which information is represented explicitly as control variables, observed memory, or communication flags.

## `ambulance_team.asl`

This policy handles discovery, reporting, pickup, and delivery. Its derived predicates include `buried_civilian`, `surface_civilian`, and `loaded`. The `+step(T)` event again enters `!saved_civilians`.

When the AmbulanceTeam finds a buried civilian, it can use `!told_fire(Civ)` and `notify_fire_needed` to request rescue. If it knows the civilian is at the surface, it enters `!loaded(Civ)`. That goal moves toward the civilian, waits when the civilian is not yet ready, and executes `load(Civ)` once its preconditions are satisfied. `!delivered(Civ)` brings a loaded civilian to a refuge and executes `unload`. The program also handles reports from FireBrigade, remembered pickup locations, discovered refuges, and routine patrol.

The `!patrol` and `!visit(Pos)` plans have location preferences similar to the FireBrigade's, but the AmbulanceTeam can also be redirected by a carried civilian or a reported pickup. These distinctions explain why the RCRS translation needs both an agent's current task stage and its search history. The concrete state change caused by loading or unloading is still encoded in the baseline ISPL evolution rules.

## `blue_agent.asl`

This is the defensive policy for the CAGE experiments. It starts from `+step(T)`, which calls `!observe_network`. The configured belief `expected_host_count(13)` is a parameter of this source program. A generated mapping can use a different selected host set; this does not mean that the whole 13-host Jason runtime is executed in a smaller ISPL example.

The belief-update plans process `host_state(Host, Activity, Compromised)` reports. A clean report can mark a host as secure. Suspicious activity can identify the initial foothold, which the policy intentionally skips when choosing remediation. Other suspicious reports can remove the `secure(Host)` belief. This is based on reported activity and compromise levels, not direct access to hidden network state.

After the expected reports have been collected, `!observe_network` enters `!secure_network`. That goal gives priority to `Op_Server0` and then selected enterprise hosts. It next considers other reported insecure hosts. If no further host requires work, it calls `monitor`. The goal `!secure(Host)` makes the response choice: it skips the initial foothold and Defender, restores a host with a `"privileged"` compromise report, and removes one with a `"user"` report. Its final plan is a fallback.

For example:

```asl
+!secure(Host) : host_state(Host, _, "privileged") <-
   .print("[Alert]: ", Host, " is compromised (privileged). Executing RESTORE.");
   +secure(Host);
   restore(Host).
```

The translator does not execute `.print`, wait for simulator observations, or update a complete Jason belief base. The mapping grounds selected `Host` terms, associates report predicates with ISPL conditions, and maps `restore(Host)` or `remove(Host)` to specific Blue actions. Some actions are retained independently through `pass_through` rules, so the guided model is deliberately a selected-policy abstraction.

## `blue_agent_old.asl`

This is an earlier, much smaller Blue example. It enters `!defend` and chooses restore, remove, or monitor from simple `alerted` and `malicious` conditions. It is not the Blue source referenced by the current CAGE example mappings. I keep it for comparison with the more detailed `blue_agent.asl`, not as the program used to produce the current CAGE results.

## How these files connect to the examples

Each `examples/<name>/input/jason_mapping.json` identifies the source program under `jason.roles.<role>.program`, the MCMAS agent under `ispl_agent`, and the entry event under `entry_goal`. The translator reads the specified source, finds reachable achievement goals, builds the task-control states, and uses the mapped plans to restrict legal baseline actions. For the meaning of every mapping field, see [`examples/MAPPING_GUIDE.md`](../examples/MAPPING_GUIDE.md). For the implementation, start with [`src/jason_guided.md`](../src/jason_guided.md).
