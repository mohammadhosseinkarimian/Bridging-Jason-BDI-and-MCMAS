# Paper edits with explicit goal control

Line numbers refer to the original Example (1).tex. Apply from bottom to top.
Keep original lines 112–165, including the hierarchical Jason and goal-level ISPL examples. The earlier instructions to replace them with a reactive policy are superseded.

1. After line 8, insert:

```latex
\usepackage{float}
```

2. In line 28, replace only the sentence beginning In the 13-host configuration with:

```latex
In the five-host and thirteen-host configurations, the counts decrease from 3,903 and 32,559, respectively, to 97 states in each Jason-guided model.
```

3. After line 107, insert:

```latex
The simple configuration contains one user host, one enterprise host,
one operational host, Defender, and the operational server, giving five
hosts in total. The complete configuration contains the thirteen hosts
described above. In both generated baselines, Red follows a directed
B-line abstraction through the enterprise gateway to
\texttt{Op\_Server0}. The gateway is \texttt{Enterprise0} in the simple
configuration and \texttt{Enterprise2} in the complete configuration.
Failed operational discovery or impact after restoration resets the
relevant access record so that Red retries. Within each baseline--guided
pair, this Red policy and the Environment rules are identical.
The mapping retains the original goal domains. Apart from the initial
foothold, hosts outside the attack route have invariant clean reports,
allowing their security predicates
to be fixed without removing their goal labels.
```

4. After line 165, insert:

```latex
For the simple and complete configurations, three CTL reachability
queries complement the two ATL strategic queries. The simple
configuration uses the following MCMAS formula section:

\begin{verbatim}
Formulae
    EF Enterprise0_root;
    EF OpServer_root;
    EF OTService_impacted;
    <red_team> F OTService_impacted;
    <blue_team> G OTService_running;
end Formulae
\end{verbatim}

The complete configuration replaces the first query with
\texttt{EF Enterprise2\_root;}. The remaining four are unchanged.
The first three ask whether gateway compromise, server compromise,
and service disruption are possible. The last two ask whether Red
can force disruption and whether Blue can guarantee availability.
Their results, in this order, are \texttt{true}, \texttt{true},
\texttt{true}, \texttt{false}, and \texttt{true} in both members
of each pair.
```

5. Replace original lines 169–180 with:

```latex
In the two-host comparison, the baseline has 20 reachable states and
the Jason-guided model has 14. The four ATL queries retain the results
\texttt{true}, \texttt{true}, \texttt{false}, and \texttt{true},
respectively. Root access and service disruption remain possible,
Red cannot force disruption, and Blue retains a winning strategy for
availability under the perfect-information semantics used here.
This ability includes the retained restoration choice and does not
establish an observation-uniform strategy for the original Jason agent.

\paragraph{Five-host and thirteen-host configurations.}
Table~\ref{tab:runtime} reports the results for the simple and complete
configurations. Every guided model retains an explicit
\texttt{blue\_goal\_level} variable, its original goal domain,
goal-dependent protocol rules, and goal-adoption and completion updates.
Additional reachability checks confirm that the network and attacked-host
goal stages can be reached and that host-security stages can return to
the network-security goal. All six CAGE models are deadlock-free,
and the original property results are preserved within each pair.

We used MCMAS~1.3.0 on Ubuntu~24.04 under WSL2, without model export.
The simple pair uses \texttt{-o 1}, and the complete pair uses
\texttt{-o 1 -g 1}. Each setting is applied identically to the baseline
and guided model of its pair. These options change BDD ordering and
grouping; they do not change the goal domains or model semantics.
Each model had one excluded warm-up run followed by 11 measured runs.
Runs were serial, with baseline and guided order alternating between
repetitions. Times are median elapsed wall-clock times measured using
a monotonic clock. BDD memory is MCMAS's reported memory in use,
converted from bytes to decimal MB.

\begin{table}[H]
\caption{MCMAS results for the CAGE baseline and Jason-guided models.}
\label{tab:runtime}
\centering
\small
\setlength{\tabcolsep}{3pt}
\begin{tabular}{lrrr}
\hline
Model & States & Time (s) & BDD memory (MB) \\
\hline
Simple baseline & 3,903 & 0.519 & 13.998 \\
Simple Jason-guided & 97 & 0.503 & 13.943 \\
Complete baseline & 32,559 & 16.693 & 41.807 \\
Complete Jason-guided & 97 & 15.205 & 31.357 \\
\hline
\end{tabular}
\end{table}

The reachable state space decreases by approximately 97.51\%
in the simple configuration and 99.70\% in the complete
configuration. These counts include the explicit goal-control state.
With the stated BDD settings, median execution time in the simple
configuration decreases from 0.519 to 0.503~seconds.
With the stated BDD settings, median execution time in the complete
configuration decreases from 16.693 to 15.205~seconds.
The cost comparison depends on the symbolic encoding. With MCMAS's
default BDD settings, the guided models still have fewer reachable
states, but the measured verification times are higher in both larger
configurations. Thus, the table does not establish a speedup independent
of the chosen BDD ordering.
In the two-host example, default BDD memory changes from 9.177
to 9.218~MB, while median elapsed time changes
from 0.048 to 0.046~seconds.
A smaller reachable set therefore does not guarantee lower verification
time or BDD memory. The control state and its transition relation also
contribute to verification costs.

The guided models retain the baseline Red and Environment blocks,
initial domain states, and physical action effects. The restrictions
apply to Blue's decisions, together with the added goal-control state.
The results concern the directed attacker and the selected hierarchical
mapping described here. The verification does not establish a cumulative
reward for the original CybORG agent, since the finite model does not
encode the challenge reward function.
```

Keep the final discussion paragraph at original line 182. The updated full source is docs/ICAART2027_updated.tex.
