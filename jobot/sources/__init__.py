"""Registry of job sites. Keys match the `sources:` section of config.yaml."""

from . import (company_pages, ikman, itpro, lankajobs, linkedin, observerjobs, rooster, rss, techjobs, topjobs,
               xpressjobs)

SOURCES = {
    "topjobs": topjobs,
    "xpressjobs": xpressjobs,
    "ikman": ikman,
    "rooster": rooster,
    "observerjobs": observerjobs,
    "lankajobs": lankajobs,
    "itpro": itpro,
    "techjobs": techjobs,
    "rss": rss,
    "company_pages": company_pages,
    "linkedin": linkedin,
}
