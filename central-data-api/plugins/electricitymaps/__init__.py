from .api import router, startup
from .models import ElectricityMapsCarbonIntensity, APICache

# IMPORTANT: These variables are searched for by discover_and_load_plugins()
router = router
#... APICache -> für Proxy eingefügt
models = [ElectricityMapsCarbonIntensity, APICache]
startup = startup