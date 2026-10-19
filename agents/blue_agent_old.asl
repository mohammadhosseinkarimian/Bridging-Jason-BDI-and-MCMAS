+step(T) : true <- !defend.
+!defend : alerted <- restore; ?defend.
+!defend : malicious <- remove; ?defend.
+!defend : true <- monitor; ?defend.
