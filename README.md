# Machine a laver intelligente

Integration Home Assistant pour inferer automatiquement le cycle d'une machine a laver a partir des capteurs deja presents dans HA.

Cette premiere version ne depend pas d'une API constructeur. Elle fonctionne surtout avec:

- un capteur de puissance obligatoire
- un capteur de vibration optionnel
- un capteur de porte optionnel

L'integration expose:

- le statut global (`idle`, `running`, `finished`)
- la phase actuelle (`starting`, `heating`, `washing`, `rinsing`, `spinning`, `cooldown`)
- le programme probable le plus proche des cycles appris
- un bouton de calibration pour apprendre un cycle reel
- le temps restant estime
- l'heure de fin estimee

## Limite importante

Le "mode exact" d'une machine a laver ne peut pas etre detecte de maniere fiable avec un simple on/off.

Cette integration produit donc:

- un programme probable
- un score de proximite
- une estimation de fin
- une lecture de phase en temps reel

La precision depend directement du capteur de puissance, du pas de rafraichissement et du comportement reel de la machine.

## Installation

1. Copier `custom_components/washing_machine_assistant` dans `config/custom_components`
2. Redemarrer Home Assistant
3. Ajouter l'integration depuis l'interface
4. Choisir au minimum le capteur de puissance de la machine

## Reglages conseilles

- `start_power_w`: puissance a partir de laquelle un cycle semble demarrer
- `stop_power_w`: puissance en dessous de laquelle la machine est consideree inactive
- `high_power_w`: seuil utilise pour reconnaitre les phases de chauffe
- `finish_grace_minutes`: delai d'inactivite avant de declarer le cycle termine
- `reset_finished_minutes`: duree pendant laquelle l'etat `finished` reste visible

Pour une prise connectee classique, un point de depart raisonnable est:

- `start_power_w = 8`
- `stop_power_w = 3`
- `high_power_w = 1200`
- `finish_grace_minutes = 5`
- `reset_finished_minutes = 180`

## Entites exposees

- `sensor.<nom>_status`
- `sensor.<nom>_phase`
- `sensor.<nom>_program`
- `sensor.<nom>_remaining_time`
- `sensor.<nom>_finish_time`
- `binary_sensor.<nom>_running`
- `binary_sensor.<nom>_finished`
- `button.<nom>_start_calibration`

## Calibration automatique

1. appuie sur le bouton `start_calibration`
2. lance le cycle ou appuie pendant qu'il tourne deja
3. l'integration attend la fin du cycle
4. elle enregistre automatiquement un nouveau mode appris

Les attributs des sensors indiquent aussi:

- `calibration_state`
- `learned_modes_count`
- `last_calibrated_mode`
- `learned_modes`
- `match_score`

## Detection du mode le plus proche

L'integration ne cherche pas un mode "exact". Elle cherche le cycle appris le plus proche a partir de:

- la duree observee
- le pic de puissance
- la part des phases de chauffe
- la part des phases proches de l'essorage
- une signature compressee de la courbe de puissance

Le resultat expose:

- `program` : le mode appris ou builtin le plus proche
- `confidence` : `low`, `medium`, `high`
- `match_score` : similarite de `0` a `100`

## Apprentissage progressif

Le fonctionnement vise maintenant ce flux:

1. tu appuies sur `start_calibration` pour enregistrer un premier vrai mode
2. tu renommes ce mode
3. les futurs cycles suffisamment proches sont rattaches automatiquement a ce mode
4. le profil est mis a jour au fil des lavages pour devenir plus representatif

Les attributs utiles:

- `last_auto_learned_mode`
- `last_auto_learned_at`

## Renommer un mode appris

Tu peux maintenant renommer un mode appris via le service:

- `washing_machine_assistant.rename_learned_mode`

Champs:

- `mode_slug`
- `new_name`
- `entity_id` optionnel si une seule machine est configuree

Le `slug` du mode est visible dans l'attribut `learned_modes` du capteur programme.

## Calibration

Pour fiabiliser le programme probable:

1. lancer plusieurs machines
2. comparer la duree reelle avec le programme detecte
3. ajuster les seuils
4. si besoin, ajouter un capteur de vibration ou de porte

## Tests locaux

```bash
python3 -m unittest discover -s tests
```
