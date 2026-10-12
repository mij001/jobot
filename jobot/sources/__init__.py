"""Registry of job sites. Keys match the `sources:` section of config.yaml."""

from . import ikman, linkedin, rooster, topjobs, xpressjobs

SOURCES = {
    "topjobs": topjobs,
    "xpressjobs": xpressjobs,
    "ikman": ikman,
    "rooster": rooster,
    "linkedin": linkedin,
}
