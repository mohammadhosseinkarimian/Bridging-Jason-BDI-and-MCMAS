# `formatting.py`: parsing, representations, and ISPL assembly

## Purpose

This module collects the pieces that both translation paths need before they can build a guided agent. It reads source files, parses the AgentSpeak subset used by the project, stores parsed plans in simple records, converts configured logical expressions, reads existing ISPL agent blocks, and writes the ordinary guided-agent blocks. Keeping these utilities outside `jason_guided.py` makes the four main translation phases easier to follow.

Despite the filename, the module is **not only concerned with indentation**. It also implements important input-processing and assembly operations. The actual choice of which actions to enable remains with `jason_guided.py` or the relation-aware translator.

## Small general utilities

`read_text(path)` loads UTF-8 text with replacement for undecodable characters. `clean_name(name)` converts a term or goal identifier to a form using letters, digits, and underscores; it prefixes identifiers that begin with a digit. `unique(values)` removes duplicates while keeping original order. `action_set` turns an action list into an ISPL `{...}` set and wraps longer lists according to the requested indentation and count per line.

`split_top(text, sep)` splits at a delimiter only when it is outside parentheses and double-quoted strings. This is why `host_state(Host, "none", "no")` can be read as a single term despite having commas inside it. It is a practical scanner for the syntax used here, not a complete expression parser.

## Structured representations

The module defines five `dataclass` records:

| Class | Fields and purpose |
| --- | --- |
| `Term` | `op`, `name`, `args`, `raw`. One parsed Jason body term, including an optional `+`, `-`, `!`, or `?` prefix. |
| `Plan` | `goal`, `context`, `body`, `terms`, `index`. One `+!` plan with its original source order. |
| `GoalCall` | `parent`, `child`, `plan_index`. A reachable achievement-goal call. |
| `GoalControl` | `top`, `values`, `calls`, `reachable`. The extracted task structure and finite control values. |
| `AgentSpec` | `role_key`, `plans`, `control`, `stages`, `ranking_goal`, `ranking_order`. The record passed to protocol and evolution generation. |

These records are the interface between parsing and model generation. Once the plans are in this form, the main algorithm no longer needs to deal with raw multiline AgentSpeak text at every step.

## Reading AgentSpeak plans

`parse_term` removes the optional term operator, recognizes a predicate/action name, and reads parenthesized arguments. `_parse_body_terms` splits the body at top-level semicolons and parses each part. `_strip_asl_comments` removes `//` comments before plan parsing.

`read_plans(asl_text, entry_goal)` scans for supported `+!` achievement-goal plans and stores their triggering goal, context, body terms, and source index. It determines the starting task from an achievement-goal call in the configured entry goal's plan. For example, `+step(T) <- !saved_civilians` supplies `saved_civilians` as the top task, while Blue's `!observe_network` entry leads to `secure_network` when the relevant call is found.

The parser is deliberately limited. It does not provide Jason's complete syntax, unification, test-goal execution, event scheduling, or plan-failure semantics. A plan that cannot be represented by the supported pattern may not be extracted, which is one reason to keep the mapping and resulting ISPL under review.

## Grounding parameterized programs

`ground_program(text, config)` handles a configuration such as:

```json
{
  "variable": "Host",
  "members": ["User0", "Op_Server0"],
  "values": ["no", "user", "privileged"],
  "signatures": {
    "host_state": [0, 2],
    "secure": [0],
    "restore": [0],
    "remove": [0]
  }
}
```

It duplicates relevant `+!` plan text for the configured `members`, replaces the selected variable, simplifies certain equalities between literal strings, and turns listed terms into normalized names. With `host_state: [0,2]`, the first and third arguments are used in a normalized predicate name such as `host_state_Op_Server0_privileged`. For an action `restore(Host)`, `restore: [0]` produces a host-specific normalized action such as `restore_Op_Server0`.

Grounding is based on the declared signatures. It is not a general theorem prover or a full AgentSpeak runtime. If the signature is missing or a term cannot be matched, that term is not necessarily grounded into the form expected by the mapping.

`action_category`, `context_has`, and `context_has_negative` consult `jason.vocabulary`. They are used to connect source actions and predicates to stages or priority classifiers. Their matching is based on the configured names and textual contexts.

## Reading and replacing ISPL agent blocks

`parse_ispl_block` finds an `Agent NAME` through `end Agent` block and returns its start, end, and contents. `replace_ispl_agent` uses those boundaries to replace one agent with a generated block. It does not rebuild the entire ISPL document.

`parse_agent_decision` extracts four parts from an existing agent: local variable declarations, the action list, protocol rules, and evolution rules. For protocol rules it records `(condition, enabled actions)` pairs. The main translator uses this information to check that a mapped action was legal in the baseline before generating a guided rule.

This parsing uses regular expressions and expects the model's supported ISPL layout. If an unrelated file uses substantially different syntax or nested formatting, it may need its own compatibility changes. We should not treat a successful string match as a general ISPL parser.

## Translating semantic expressions from JSON

`semantic_expr(member, environment_name)` converts the condition objects used by `plan.predicates` and `plan.transitions`. These are its supported forms:

| Form | Result |
| --- | --- |
| `true`, `false`, or `null` | A constant condition (`null` is treated as true). |
| A string | Used directly as condition text. |
| `{"eq": [left, right]}` | Equality between two operands. |
| `{"neq": [left, right]}` | Negated equality. |
| `{"all": [a,b]}` | Conjunction of the child conditions. |
| `{"any": [a,b]}` | Disjunction of the child conditions. |
| `{"not": a}` | Negation of a condition. |

`_semantic_operand` handles Boolean and numeric constants, plain strings, `{"value": ...}`, and `{"env": "variable"}`. For example:

```json
{"eq": [{"env": "compromised_Op_Server0"}, "privileged"]}
```

is formatted as `Environment.compromised_Op_Server0 = privileged`. The `Environment` prefix comes from `model.environment_agent` in the mapping. The conversion is mechanical; the mapping author is responsible for choosing the correct modeled meaning of the Jason predicate.

## Writing the ordinary guided agent

`build_plain_agent_block` starts from the original agent block. It adds the new `goal_var` declaration if necessary; adds configured `extra_actions` when present; replaces the `Protocol` section with the generated rules; inserts any configured `Other: {fallback}`; and appends generated goal-control evolution rules. If no evolution rules were generated, it provides self-updates for the goal values. Existing agent evolution text is retained unless the assembled block explicitly replaces the corresponding section.

`rewrite_plain_init` locates `InitStates`, removes its old trailing separators while reading assignments, inserts the initial goal-control assignments for translated agents, and writes a syntactically assembled list back. This matters because adding a new agent variable without initializing it would make the generated model incomplete or ambiguous.

The direct path therefore uses both parsing and formatting in this file, while `jason_guided.py` decides **which plan rules to create**. The relation-aware path uses its own agent construction because it adds visited markers, shared memory, and movement rules that are not part of the plain block assembly.

## Path handling and errors

`resolve_path` treats relative configured paths as relative to the folder holding `jason_mapping.json`; `load_mapping` reads and parses that JSON. If the configuration refers to an agent that is absent from the baseline, `parse_ispl_block` raises an error. Other errors are raised when required ISPL sections cannot be found or the semantic condition object is not supported. These checks catch missing pieces, but they do not replace checking the resulting model with MCMAS.

See [`jason_guided.md`](jason_guided.md) for the translation workflow and [`../examples/MAPPING_GUIDE.md`](../examples/MAPPING_GUIDE.md) for the mapping keys in context.
