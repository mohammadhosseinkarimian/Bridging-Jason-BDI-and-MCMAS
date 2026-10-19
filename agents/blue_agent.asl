// --- CONFIGURATION ---
expected_host_count(13).


// --- STEP & BELIEF INGESTION ---
+step(T) <-
   .print("[Info]: Step ", T, " received. Ingesting host states...");
   !observe_network.

+host_state(Host, "none", "no") : not secure(Host) <-
    .print("[Info]: Host '", Host, "' is clean. No action required.");
    +secure(Host).

// Initial foothold detection (captures first host showing scan activity)
+host_state(Host, Activity, Compromised) : (Activity \== "none" | Compromised \== "no") & not initial_foothold(_) <-
   .print("[Info]: Host '", Host, "' identified as Red initial foothold. Remediation will be bypassed.");
   +initial_foothold(Host).


// for the next interation, we can more specifically address unknown compromised status on hosts 
+host_state(Host, Activity, Compromised) : not initial_foothold(Host) & (Activity \== "none" | Compromised == "user" | Compromised == "privileged") <-
   .print("[Warning]: Activity detected on Host: '", Host, "'");
   -secure(Host).


// --- NETWORK EVALUATION GATE ---
+!observe_network : expected_host_count(N) & .count(host_state(_, _, _)) == N <-
   .print("[Info]: All ", N, " hosts received in belief base. Starting security sweep...");
   !secure_network.


// --- PRIORITY SECURITY SWEEP ---
+!secure_network : not secure("Op_Server0") <-
   .print("[Priority Sweep]: High-priority asset 'Op_Server0' detected. Executing remediation first.");
   !secure("Op_Server0").

+!secure_network : not secure("Enterprise0") <-
   .print("[Priority Sweep]: High-priority asset 'Enterprise0' detected. Executing remediation first.");
   !secure("Enterprise0").

+!secure_network : not secure("Enterprise1") <-
   .print("[Priority Sweep]: High-priority asset 'Enterprise1' detected. Executing remediation first.");
   !secure("Enterprise1").

+!secure_network : not secure("Enterprise2") <-
   .print("[Priority Sweep]: High-priority asset 'Enterprise2' detected. Executing remediation first.");
   !secure("Enterprise2").

// Sweeps remaining unsecure hosts
+!secure_network : host_state(Host, _, _) & not secure(Host) <-
   .print("[Security Sweep]: Asset '", Host, "' detected. Executing remediation.");
   !secure(Host).

// All host secured
+!secure_network <-
   .print("[Info]: Security sweep complete. All hosts secured.");
   monitor.


// --- SECURING INDIVIDUAL HOSTS ---
+!secure(Host) : initial_foothold(Host) <-
   .print("[Info]: Skipping remediation on initial foothold: ", Host);
   +secure(Host).

+!secure(Host) : Host == "Defender" <-
   .print("[Info]: Skipping remediation on Defender.");
   +secure(Host).

+!secure(Host) : host_state(Host, _, "privileged") <-
   .print("[Alert]: ", Host, " is compromised (privileged). Executing RESTORE.");
   +secure(Host);
   restore(Host).

+!secure(Host) : host_state(Host, _, "user") <- 
   .print("[Alert]: ", Host, " is compromised (user). Executing REMOVE.");
   +secure(Host);
   remove(Host).

// Fallback plan
+!secure(Host) <- 
   .print("[Info]: Host ", Host, " evaluated under fallback policy.");
   +secure(Host);
   !secure_network.