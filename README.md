# 🫧 Machine a laver intelligente

Integration Home Assistant pour suivre une machine a laver a partir des capteurs deja presents dans HA, sans API constructeur.

Elle fonctionne surtout avec:

- un capteur de puissance obligatoire
- un capteur de vibration optionnel
- un capteur de porte optionnel

L'integration expose:

- un statut global en temps reel
- une phase probable du cycle
- un programme probable
- un bouton de calibration pour apprendre un vrai cycle
- un temps restant estime
- une heure de fin estimee

## ⚠️ Limite importante

Le mode exact d'une machine a laver ne peut pas etre determine de maniere parfaitement fiable a partir de la seule puissance.

L'integration cherche donc a fournir:

- un programme probable
- un score de proximite
- une estimation de fin
- une lecture de phase en temps reel

La precision depend directement:

- de la qualite du capteur de puissance
- de la frequence de rafraichissement
- du comportement reel de la machine
- de la qualite des cycles appris

## 🚀 Installation

1. Copier `custom_components/washing_machine_assistant` dans `config/custom_components`
2. Redemarrer Home Assistant
3. Ajouter l'integration depuis l'interface
4. Choisir au minimum le capteur de puissance de la machine

Au premier ajout, le flow principal reste volontairement simple:

- nom
- capteur de puissance
- capteur de vibration optionnel
- capteur de porte optionnel

Les seuils avances restent disponibles ensuite dans les options de l'integration si tu veux reprendre la main.

## ⚙️ Reglages avances

En usage normal, il n'est pas necessaire de tout regler au premier demarrage:

- l'integration part de valeurs internes prudentes
- elle apprend ensuite a partir des cycles observes
- elle expose ses ajustements dans `adaptive_thresholds`

Les principaux reglages avances sont:

- `start_power_w`: puissance a partir de laquelle un cycle semble demarrer
- `stop_power_w`: puissance en dessous de laquelle la machine est consideree inactive
- `high_power_w`: seuil utilise pour reconnaitre les phases de chauffe
- `finish_grace_minutes`: delai d'inactivite avant de declarer le cycle termine
- `reset_finished_minutes`: duree pendant laquelle l'etat termine reste visible
- `update_interval_seconds`: frequence de rafraichissement

Point important:

- `start_power_w` sert au demarrage
- `stop_power_w` sert a reconnaitre la vraie fin du cycle
- la calibration n'est donc pas stoppee au premier creux de puissance

## 🧩 Entites exposees

Les noms visibles dans Home Assistant dependent de la langue de l'interface. En francais, tu verras typiquement:

- `sensor.machine_a_laver_statut`
- `sensor.machine_a_laver_phase`
- `sensor.machine_a_laver_programme_probable`
- `sensor.machine_a_laver_temps_restant`
- `sensor.machine_a_laver_heure_de_fin`
- `sensor.machine_a_laver_statut_calibration`
- `binary_sensor.machine_a_laver_en_cours`
- `binary_sensor.machine_a_laver_termine`
- `button.machine_a_laver_demarrer_calibration`

Si ton interface HA est dans une autre langue, les `entity_id` peuvent differer.

## 👀 Etats visibles

L'interface affiche maintenant des libelles francais, par exemple:

- statut: `Inactif`, `En cours`, `Termine`, `Indisponible`
- phase: `Demarrage`, `Chauffe`, `Lavage`, `Rincage`, `Essorage`, `Retour au calme`, `Inconnu`
- calibration: `Inactive`, `Calibration armee`, `En cours de calibration`

Pour les automatisations ou le debug, les attributs conservent aussi des valeurs techniques:

- `status_raw`
- `phase_raw`
- `confidence`
- `program_source`

Des libelles supplementaires sont aussi exposes:

- `confidence_label`
- `program_source_label`

## 🎯 Calibration

La calibration sert a enregistrer un vrai cycle de ta machine.

Procedure recommandee:

1. verifier que la machine est au repos
2. choisir le programme sur la machine
3. appuyer sur `Demarrer calibration`
4. lancer immediatement le cycle
5. laisser la machine aller jusqu'a la fin reelle

Comportement actuel:

- la calibration commence des le clic
- elle peut donc enregistrer meme si la prise est encore a `0 W`
- elle continue pendant tout le cycle
- elle s'arrete automatiquement quand la fin reelle est detectee
- elle attend la temporisation de fin de cycle avant de cloturer

Attributs utiles pendant la calibration:

- `calibration_state`
- `calibration_status`
- `learned_modes_count`
- `last_calibrated_mode`
- `learned_modes`
- `match_score`

## 🧠 Detection du mode le plus proche

L'integration ne cherche pas un mode exact. Elle cherche le cycle appris ou integre le plus proche a partir de:

- la duree observee
- le pic de puissance
- la part des phases de chauffe
- la part des phases proches de l'essorage
- une signature compressee de la courbe de puissance

Le resultat expose notamment:

- `programme probable`
- `confidence` / `confidence_label`
- `match_score`
- `program_source` / `program_source_label`

## 📈 Apprentissage progressif

Le fonctionnement vise ce flux:

1. tu appuies sur `Demarrer calibration` pour enregistrer un premier vrai mode
2. tu renommes ce mode
3. les futurs cycles suffisamment proches sont rattaches automatiquement a ce mode
4. le profil est mis a jour au fil des lavages pour devenir plus representatif

Attributs utiles:

- `last_auto_learned_mode`
- `last_auto_learned_at`
- `adaptive_thresholds`

L'integration peut aussi ajuster progressivement ses seuils runtime a partir des cycles observes:

- `start_power_w`
- `stop_power_w`
- `high_power_w`

Les valeurs configurees restent la base initiale. Les valeurs adaptees sont exposees dans `adaptive_thresholds`.

## 🔌 Tolerance aux coupures de prise

Si le capteur de puissance passe brievement en `unavailable`, l'integration peut reutiliser temporairement la derniere valeur valide au lieu de casser le cycle.

Attributs utiles:

- `power_source`: `live`, `cached` ou `missing`
- `power_unavailable_seconds`

## ✏️ Renommer un mode appris

Tu peux renommer un mode appris via le service:

- `washing_machine_assistant.rename_learned_mode`

Champs:

- `mode_slug`
- `new_name`
- `entity_id` optionnel si une seule machine est configuree

Le `slug` du mode est visible dans l'attribut `learned_modes` du capteur programme.

## ✅ Conseils pratiques

Pour fiabiliser le programme probable:

1. calibrer les vrais programmes que tu utilises
2. laisser les cycles aller jusqu'a la fin reelle
3. verifier de temps en temps `learned_modes` et `adaptive_thresholds`
4. ajouter un capteur de vibration ou de porte si tu veux encore plus de robustesse

## 🧪 Tests locaux

```bash
python3 -m unittest discover -s tests
```
