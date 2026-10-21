"""Registry of job sites. Keys match the `sources:` section of config.yaml."""

from . import (company_pages, ikman, itpro, jooble, lankajobs, linkedin, mailbox, observerjobs, remote, rooster, rss,
               techjobs, topjobs, xpressjobs)

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
    "email_alerts": mailbox,
    "jooble": jooble,
    "remote_jobs": remote,
}
