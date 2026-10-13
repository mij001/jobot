"""Registry of job sites. Keys match the `sources:` section of config.yaml."""

from . import company_pages, ikman, lankajobs, linkedin, observerjobs, rooster, rss, topjobs, xpressjobs

SOURCES = {
    "topjobs": topjobs,
    "xpressjobs": xpressjobs,
    "ikman": ikman,
    "rooster": rooster,
    "observerjobs": observerjobs,
    "lankajobs": lankajobs,
    "rss": rss,
    "company_pages": company_pages,
    "linkedin": linkedin,
}
