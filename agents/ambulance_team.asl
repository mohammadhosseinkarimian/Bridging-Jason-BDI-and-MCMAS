at_area(Pos) :-
    my_id(AT) & at(AT, Pos).

alive(Civ) :-
    civilian(Civ) & health(Civ, Health) & Health \== dead.

buried_civilian(Civ, Pos, Level) :-
    civilian(Civ) &  alive(Civ) &  buried_victim(Civ, Pos, Level) &  Level \== surface.

surface_civilian(Civ, Pos) :-
    civilian(Civ) & alive(Civ) & buriedness(Civ, surface) & at(Civ, Pos) & area(Pos) & not refuge(Pos).

loaded(Civ) :-
    my_id(AT) & civilian(Civ) & at(Civ, AT).

+rescued(Civ) : buried_victim(Civ, Pos, Level) <- -buried_victim(Civ, Pos, Level).

+step(T) : true <- !saved_civilians.

+!saved_civilians : delivered(Civ) <-
    !patrol; ?saved_civilians.

+!saved_civilians : loaded(Civ) <-
    !delivered(Civ); ?saved_civilians.

+!saved_civilians : buried_civilian(Civ, Pos, Level) & not found_civilian(Civ, Pos) <-
    !found_civilian(Civ, Pos); !told_fire(Civ); ?saved_civilians.

+!saved_civilians : found_civilian(Civ, Pos) & buried_civilian(Civ, Pos, Level) & not told_fire(Civ) <-
    !told_fire(Civ); ?saved_civilians.

+!saved_civilians : surface_civilian(Civ, Pos) & not found_civilian(Civ, Pos) <-
    !found_civilian(Civ, Pos); !loaded(Civ); ?saved_civilians.

+!saved_civilians : found_civilian(Civ, Pos) & surface_civilian(Civ, Pos) <-
    !loaded(Civ); ?saved_civilians.

+!saved_civilians : ready_for_pickup(Civ, Pos) & not pickup_needed(Civ, Pos) <-
    !found_civilian(Civ, Pos); +pickup_needed(Civ, Pos); !loaded(Civ); ?saved_civilians.

+!saved_civilians : fire_ready(Civ, Pos, FB) & not pickup_needed(Civ, Pos) <-
    !found_civilian(Civ, Pos); +pickup_needed(Civ, Pos); !loaded(Civ); ?saved_civilians.

+!saved_civilians : fire_done(FB, Civ, Pos) & not pickup_needed(Civ, Pos) <-
    !found_civilian(Civ, Pos); +pickup_needed(Civ, Pos); !loaded(Civ); ?saved_civilians.

+!saved_civilians : reported_transportable(Civ, Pos) & not pickup_needed(Civ, Pos) <-
    !found_civilian(Civ, Pos); +pickup_needed(Civ, Pos); !loaded(Civ); ?saved_civilians.

+!saved_civilians : reported_pickup_at(Pos) & not reported_pickup_place(Pos) <-
    +reported_pickup_place(Pos); !saved_civilians; ?saved_civilians.

+!saved_civilians : reported_pickup_place(Pos) & not at_area(Pos) <-
    log("AMB: go to reported pickup place ", Pos); move_to(Pos); ?saved_civilians.

+!saved_civilians : reported_pickup_place(Pos) & at_area(Pos) & surface_civilian(Civ, Pos) <-
    -reported_pickup_place(Pos);  !found_civilian(Civ, Pos); +pickup_needed(Civ, Pos); !loaded(Civ); ?saved_civilians.

+!saved_civilians : reported_pickup_place(Pos) & at_area(Pos) <-
    log("AMB: waiting at reported pickup place ", Pos); rest; ?saved_civilians.

+!saved_civilians : command_ambulance(_, Ref, _) & refuge(Ref) & not found_refuge(Ref) <-
    +found_refuge(Ref); !saved_civilians; ?saved_civilians.

+!saved_civilians : refuge(Ref) & not found_refuge(Ref) <-
    +found_refuge(Ref); !saved_civilians; ?saved_civilians.

+!saved_civilians : at_area(Pos) & not visited(Pos) <-
    +visited(Pos);!patrol; ?saved_civilians.

+!saved_civilians : true <-
    !patrol.

-!saved_civilians : true <- true.

+!found_civilian(Civ, Pos) : found_civilian(Civ, Pos) <- ?found_civilian(Civ, Pos).

+!found_civilian(Civ, Pos) : true <-
    +found_civilian(Civ, Pos); ?found_civilian(Civ, Pos).

-!found_civilian(Civ, Pos) : true <- true.

+!told_fire(Civ) : told_fire(Civ) <- ?told_fire(Civ).

+!told_fire(Civ) : buried_civilian(Civ, Pos, Level) <-
    +told_fire(Civ); radio_found(Civ); notify_fire_needed(Civ, Pos, Level); ?told_fire(Civ).

-!told_fire(Civ) : true <- true.

+!loaded(Civ) : loaded(Civ) <- ?loaded(Civ).

+!loaded(Civ) : pickup_needed(Civ, Pos) & found_civilian(Civ, Pos) & surface_civilian(Civ, Pos) & at_area(Pos) <-
    log("AMB: load civilian ", Civ, " at ", Pos); load(Civ); -pickup_needed(Civ, Pos); radio_loaded(Civ); ?loaded(Civ).

+!loaded(Civ) : found_civilian(Civ, Pos) & surface_civilian(Civ, Pos) & at_area(Pos) <-
    log("AMB: load civilian ", Civ, " at ", Pos); load(Civ); radio_loaded(Civ); ?loaded(Civ).

+!loaded(Civ) : pickup_needed(Civ, Pos) & found_civilian(Civ, Pos) & at_area(Pos) & not surface_civilian(Civ, Pos) <-
    log("AMB: waiting for civilian ", Civ, " at ", Pos); rest; ?loaded(Civ).

+!loaded(Civ) : found_civilian(Civ, Pos) & not at_area(Pos) <-
    log("AMB: go to found civilian ", Civ, " at ", Pos);  move_to(Pos); ?loaded(Civ).

-!loaded(Civ) : loaded(Civ) <-  ?loaded(Civ).

-!loaded(Civ) : true <- true.

+!delivered(Civ) : delivered(Civ) <- ?delivered(Civ).

+!delivered(Civ) : loaded(Civ) & found_refuge(Ref) & at_area(Ref) <-
    log("AMB: unload civilian ", Civ, " at refuge ", Ref); unload; radio_done(Civ); ?delivered(Civ).

+!delivered(Civ) : loaded(Civ) & refuge(Ref) & at_area(Ref) & not found_refuge(Ref) <-
    +found_refuge(Ref); log("AMB: unload civilian ", Civ, " at refuge ", Ref); unload; radio_done(Civ); ?delivered(Civ).

+!delivered(Civ) : loaded(Civ) & found_refuge(Ref) & not at_area(Ref) <-
    log("AMB: take civilian ", Civ, " to refuge ", Ref); move_to(Ref); ?delivered(Civ).

+!delivered(Civ) : loaded(Civ) & refuge(Ref) & not at_area(Ref) & not found_refuge(Ref) <-
    +found_refuge(Ref); log("AMB: take civilian ", Civ, " to refuge ", Ref); move_to(Ref); ?delivered(Civ).

+!delivered(Civ) : loaded(Civ) & not found_refuge(Ref) <-
    log("AMB: carrying ", Civ, " and looking for refuge"); !patrol; ?delivered(Civ).

-!delivered(Civ) : delivered(Civ) <- ?delivered(Civ).

-!delivered(Civ) : loaded(Civ) <- !delivered(Civ).

-!delivered(Civ) : true <-  true.


+!patrol : loaded(Civ) <- !delivered(Civ); ?patrol.

+!patrol : delivered(Civ) & at_area(Ref) & refuge(Ref) & known_road(Pos) & not at_area(Pos) <-
    log("AMB: leave refuge and patrol road ", Pos); move_to(Pos); ?patrol.

+!patrol : collapsed(Pos) & building(Pos) & not refuge(Pos) & not visited(Pos) & not at_area(Pos) <-
    !visit(Pos); ?patrol.

+!patrol : damaged(Pos) & building(Pos) & not refuge(Pos) & not visited(Pos) & not at_area(Pos) <-
    !visit(Pos); ?patrol.

+!patrol : building(Pos) & not refuge(Pos) & not visited(Pos) & not at_area(Pos) <-
    !visit(Pos); ?patrol.

+!patrol : road(Pos) & not visited(Pos) & not at_area(Pos) <-
    +known_road(Pos); !visit(Pos); ?patrol.

+!patrol : road(Pos) & not at_area(Pos) <-
    +known_road(Pos); log("AMB: continue patrol through road ", Pos); move_to(Pos); ?patrol.

+!patrol : known_road(Pos) & not at_area(Pos) <-
    log("AMB: continue patrol through known road ", Pos); move_to(Pos); ?patrol.

+!patrol : true <- rest.

-!patrol : true <- true.

+!visit(Pos) : loaded(Civ) <- !delivered(Civ); ?visit(Pos).

+!visit(Pos) : visited(Pos) <- true; ?visit(Pos).

+!visit(Pos) : at_area(Pos) & not visited(Pos) <- +visited(Pos); ?visit(Pos).

+!visit(Pos) : road(Pos) & not at_area(Pos) <-
    +known_road(Pos); log("AMB: patrol area ", Pos); move_to(Pos); ?visit(Pos).

+!visit(Pos) : building(Pos) & not at_area(Pos) <-
    log("AMB: patrol area ", Pos); move_to(Pos); ?visit(Pos).

-!visit(Pos) : true <- true.