"""latecup-data: the pipeline behind the Latecup late-café map."""
import os

FORMAT = 1
BASE_URL = "https://juicypasta.github.io/latecup-data/v1/"
# Sent with every request the pipeline makes (Overpass, Nominatim, NYC Open Data, All The Places, the published
# feed). It names the client and says what it does, which is what the Overpass servers ask for, and nothing about
# who runs it. A fork sets LATECUP_USER_AGENT, so its requests are not taken for this project's.
USER_AGENT = os.environ.get("LATECUP_USER_AGENT") or (
    "latecup-data/1.1 (cafes and their opening hours for a public map of coffee shops open late; "
    "a few requests a day)")
# Sent to a shop's own website when its hours are confirmed.
SHOP_USER_AGENT = "Latecup/1.0 https://juicypasta.github.io/latecup/"
