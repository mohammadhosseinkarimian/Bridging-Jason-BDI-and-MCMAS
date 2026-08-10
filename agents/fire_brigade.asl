at_area(Pos) :-
    my_id(FB) & at(FB, Pos).

alive(Civ) :-
    civilian(Civ) & health(Civ, Health) & Health \== dead.

buried_civilian(Civ, Pos, Level) :-
    alive(Civ) & at(Civ,Pos) & buriedness(Civ, Level) &  Level \== surface.

ready_for_ambulance(Civ, Pos) :-
    alive(Civ) & rescued(Civ) & at(Civ, Pos) & area(Pos) & not refuge(Pos).

+rescued(Civ) : buried_victim(Civ, Pos, Level) <-
    -buried_victim(Civ, Pos, Level).

+step(T) : true <-
    !saved_civilians.

+!saved_civilians : buried_civilian(Civ, Pos, Level) & not found_civilian(Civ, Pos) <-
    !found_civilian(Civ, Pos); !rescued_buried_civilian(Civ); ?saved_civilians.

+!saved_civilians : found_civilian(Civ, Pos) & buried_civilian(Civ, Pos, Level) <-
    !rescued_buried_civilian(Civ); ?saved_civilians.

+!saved_civilians : buried_civilian_reported(Civ, Pos) & not found_civilian(Civ, Pos) <-
    !found_civilian(Civ, Pos); !rescued_buried_civilian(Civ); ?saved_civilians.

+!saved_civilians : ready_for_ambulance(Civ, Pos) & not told_ambulance(Civ) <-
    !told_ambulance(Civ); ?saved_civilians.

+!saved_civilians : rescued(Civ) & at(Civ, Pos) & not found_civilian(Civ, Pos) <-
    !found_civilian(Civ, Pos); !told_ambulance(Civ); ?saved_civilians.

+!saved_civilians : refuge(Ref) & not told_refuge(Ref) <-
    +told_refuge(Ref); notify_ambulance_ready(Ref); !patrol; ?saved_civilians.

+!saved_civilians : at_area(Pos) & not visited(Pos) <-
    +visited(Pos); !patrol; ?saved_civilians.

+!saved_civilians : true <- !patrol.

-!saved_civilians : true <- true.

+!found_civilian(Civ, Pos) : found_civilian(Civ, Pos) <- ?found_civilian(Civ, Pos).

+!found_civilian(Civ, Pos) : true <-
    +found_civilian(Civ, Pos); ?found_civilian(Civ, Pos).

-!found_civilian(Civ, Pos) : true <- true.

+!told_ambulance(Civ) : told_ambulance(Civ) <- ?told_ambulance(Civ).

+!told_ambulance(Civ) : ready_for_ambulance(Civ, Pos) <-
    +told_ambulance(Civ); radio_done(Civ); notify_ambulance_ready(Civ, Pos); ?told_ambulance(Civ).

-!told_ambulance(Civ) : true <- true.

+!rescued_buried_civilian(Civ) : rescued(Civ) & not told_ambulance(Civ) <-
    !told_ambulance(Civ); ?rescued_buried_civilian(Civ).

+!rescued_buried_civilian(Civ) : rescued(Civ) <- ?rescued_buried_civilian(Civ).

+!rescued_buried_civilian(Civ) : found_civilian(Civ, Pos) & not at_area(Pos) <-
    log("FIRE: go to found civilian ", Civ, " at ", Pos); move_to(Pos); ?rescued_buried_civilian(Civ).

+!rescued_buried_civilian(Civ) : buried_civilian(Civ, Pos, Level) & at_area(Pos) <-
    radio_busy(Civ); log("FIRE: rescue civilian ", Civ, " at ", Pos, " buriedness=", Level); rescue(Civ); ?rescued_buried_civilian(Civ).

-!rescued_buried_civilian(Civ) : true <- true.


+!patrol : found_civilian(Civ, Pos) & buried_civilian(Civ, Pos, Level) & area(Pos) & not at_area(Pos) <-
    log("FIRE: patrol to found civilian ", Civ, " at ", Pos, " buriedness=", Level); move_to(Pos); ?patrol.

+!patrol : buried_civilian(Civ, Pos, Level) & area(Pos) & not at_area(Pos) <-
    log("FIRE: patrol to buried civilian ", Civ, " at ", Pos, " buriedness=", Level); move_to(Pos); ?patrol.

+!patrol : collapsed(Pos) & building(Pos) & not visited(Pos) & not at_area(Pos) <-
    !visited(Pos); ?patrol.

+!patrol : damaged(Pos) & building(Pos) & not visited(Pos) & not at_area(Pos) <-
    !visited(Pos); ?patrol.

+!patrol : building(Pos) & not visited(Pos) & not at_area(Pos) <-
    !visited(Pos); ?patrol.

+!patrol : road(Pos) & not visited(Pos) & not at_area(Pos) <-
    !visited(Pos); ?patrol.

+!patrol : road(Pos) & not at_area(Pos) <-
    log("FIRE: continue patrol through road ", Pos); move_to(Pos); ?patrol.

+!patrol : true <- rest.

-!patrol : true <- true.

+!visited(Pos) : visited(Pos) <- true; ?visited(Pos).

+!visited(Pos) : at_area(Pos) & not visited(Pos) <-
    +visited(Pos); ?visited(Pos).

+!visited(Pos) : not at_area(Pos) <-
    log("FIRE: patrol area ", Pos); move_to(Pos); ?visited(Pos).

-!visited(Pos) : true <- true.