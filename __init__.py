from .quick_map_compare import QuickMapComparePlugin


def classFactory(iface):
    return QuickMapComparePlugin(iface)
