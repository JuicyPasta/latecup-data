"""latecup-data: the pipeline behind the Latecup late-café map."""

FORMAT = 1
BASE_URL = "https://juicypasta.github.io/latecup-data/v1/"
# Sent to Overpass and NYC Open Data.
USER_AGENT = "latecup-data/1.0 (+https://github.com/JuicyPasta/latecup-data)"
# Sent to a shop's own website when its hours are confirmed.
SHOP_USER_AGENT = "Latecup/1.0 https://juicypasta.github.io/latecup/"
