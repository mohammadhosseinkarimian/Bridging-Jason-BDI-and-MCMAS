// Reactive security sweep for one defensive decision per Blue turn.
// The host set and report predicates are grounded by jason_mapping.json.
+step(T) : true <- !observe_network.

+!observe_network : true <- !secure_network.

// Preserve the original policy's server-first response priority.
+!secure_network : host_state("Op_Server0", _, "privileged") <-
    restore("Op_Server0").

+!secure_network : host_state("Op_Server0", _, "user") <-
    remove("Op_Server0").

// Remaining hosts are grounded in enterprise-first order. The mapping
// excludes the initial foothold and Defender, as in blue_agent.asl.
+!secure_network : host_state(Host, _, "privileged") <-
    restore(Host).

+!secure_network : host_state(Host, _, "user") <-
    remove(Host).

+!secure_network : true <- monitor.
