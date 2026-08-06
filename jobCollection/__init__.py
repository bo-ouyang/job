import os

# The Scrapy source package lives one level below this project package.  Make
# it visible when tests and tools import from the repository root.
_scrapy_package = os.path.join(os.path.dirname(__file__), "jobCollection")
if _scrapy_package not in __path__:
    __path__.append(_scrapy_package)
