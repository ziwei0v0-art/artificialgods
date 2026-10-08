"""v0.4 A.1 trial defaults; no economy, capacity, or genetic upgrades.

The 30-second first breed after an empty-field refill is the existing verified
prototype safeguard. New action lengths and the 21:00–05:00 rest window are
presentation/scheduling defaults, not claims about real religious practice.
"""

COLORS = ('普通褐色', '中褐色', '深褐色', '白色')
PRICES = dict(zip(COLORS, (1, 2, 3, 8)))
SHOP = {
    'offering_plate': {'name': '素色供盘', 'price': 12, 'slot': 'plate'},
    'incense_burner': {'name': '陶香炉', 'price': 24, 'slot': 'incense'},
    'bell': {'name': '小铜铃', 'price': 60, 'slot': 'bell'},
    'shrine_g1': {'name': '神龛整修', 'price': 120, 'slot': 'shrine'},
    'shrine_g2': {'name': '彩绘与局部贴金', 'price': 360, 'slot': 'shrine',
                  'requires': 'shrine_g1'},
}

FIRST_SPAWN_SECONDS = 15
FIRST_SPAWN_COUNT = 6
EMPTY_REFILL_SECONDS = 60
REFILL_COUNT = 2
BREED_INTERVAL_SECONDS = 60
REFILL_FIRST_BREED_SECONDS = 30
BREED_BATCH_MAX = 4
DESKTOP_SOFT_LIMIT = 24
AUTO_CAPTURE_INTERVAL_SECONDS = 45
AUTO_CAPTURE_LIMIT = 24 * 60 * 60

FRUIT_RIPEN_SECONDS = 60
FRUIT_SOFT_FRACTION = 0.5
OFFER_SECONDS = 8
PRACTICE_SECONDS = 45
PRACTICE_WINDOWS = (('morning', 5, 7), ('evening', 17, 19))
NIGHT_START_HOUR = 21
NIGHT_END_HOUR = 5
CATCH_SECONDS = 3
BELL_SECONDS = 4
REST_SECONDS = 60
AMBIENT_CYCLE = (('walk', 5), ('sweep', 12), ('idle', 8),
                 ('walk', 5), ('read', 18), ('idle', 8))
