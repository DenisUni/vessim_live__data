from .api import router, startup
from .models import ElectricityMapsCarbonIntensity

# IMPORTANT: These variables are searched for by discover_and_load_plugins()
router = router
models = [ElectricityMapsCarbonIntensity]  # List of SQLModel classes
startup = startup