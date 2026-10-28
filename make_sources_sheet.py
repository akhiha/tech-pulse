"""Build Tech-Pulse-Sources.xlsx from feeds.json + feed_check.json so the user can pick sources."""
import json
from datetime import datetime

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

INFO = {  # name -> (type, what it covers)
    "Anthropic": ("Official company site (scraped, no feed)", "Anthropic announcements: Claude models, products, policy"),
    "Thoughtworks": ("Official company blog", "Thoughtworks insights: AI in delivery, architecture, tech strategy"),
    "Anthropic Engineering": ("Official company site (scraped, no feed)", "How Anthropic builds agents, Claude Code and its infrastructure"),
    "Anthropic Research": ("Official company site (scraped, no feed)", "Anthropic research: alignment, interpretability, AI and the economy"),
    "Qwen": ("Official lab blog", "Alibaba's Qwen model releases"),
    "Airbnb Engineering": ("Engineering blog", "Search, ML and infrastructure at Airbnb"),
    "Spotify Engineering": ("Engineering blog", "Recommendation systems and platform engineering at Spotify"),
    "Stripe": ("Official company blog", "Payments infrastructure and Stripe engineering"),
    "Slack Engineering": ("Engineering blog", "Slack's infrastructure and developer tooling"),
    "Dropbox Tech": ("Engineering blog", "Storage, infrastructure and AI at Dropbox"),
    "Pinterest Engineering": ("Engineering blog", "ML, data and infrastructure at Pinterest"),
    "Shopify Engineering": ("Engineering blog", "Commerce platform engineering at Shopify"),
    "Lyft Engineering": ("Engineering blog", "Marketplace, mapping and data engineering at Lyft"),
    "Datadog Engineering": ("Engineering blog", "Observability, distributed systems and security at Datadog"),
    "GitHub Engineering": ("Engineering blog", "How GitHub runs Git and its platform at scale"),
    "ByteByteGo": ("Newsletter", "System design explainers on how big companies build their systems"),
    "Google for Developers": ("Official company blog", "Gemini API, Android, Chrome and Google developer tools"),
    "IEA": ("International agency (via Google News)", "International Energy Agency reports, analysis and news"),
    "Green Software Foundation": ("Industry body", "Standards and research on sustainable software"),
    "The Verge": ("News site", "Consumer tech, gadgets, platforms, policy"),
    "TechCrunch": ("News site", "Startups, funding, venture capital, product launches"),
    "Ars Technica": ("News site", "In-depth tech, science, IT and policy"),
    "Wired": ("News site", "Tech culture, business, science, security"),
    "Engadget": ("News site", "Gadgets, gaming, consumer electronics"),
    "The Register": ("News site", "Enterprise IT, cloud, sysadmin, chips (UK)"),
    "MIT Technology Review": ("News site", "Emerging tech, AI, biotech, climate tech"),
    "Techmeme": ("Aggregator", "The day's top tech stories from across the web"),
    "Hacker News (150+ pts)": ("Aggregator", "Popular Hacker News links (150+ points only)"),
    "Rest of World": ("News site", "Tech outside the US and Europe (Asia, Africa, LatAm)"),
    "The Next Web": ("News site", "European tech, startups, deep tech"),
    "9to5Mac": ("News site", "Apple, iPhone, Mac (high volume)"),
    "9to5Google": ("News site", "Google, Android, Pixel (high volume)"),
    "Google": ("Official company blog", "Google's own announcements (The Keyword)"),
    "Microsoft": ("Official company blog", "Microsoft corporate announcements"),
    "Apple Newsroom": ("Official company blog", "Apple press releases"),
    "Meta Engineering": ("Official company blog", "Meta engineering: infra, AI, open source"),
    "AWS News": ("Official company blog", "New AWS services and launches"),
    "NVIDIA": ("Official company blog", "GPUs, AI computing, data centres"),
    "OpenAI": ("Official company blog", "OpenAI model releases, research, product news"),
    "Google DeepMind": ("Official company blog", "DeepMind research and model releases"),
    "Samsung Newsroom": ("Official company blog", "Samsung devices, chips, press releases"),
    "Netflix Tech Blog": ("Official company blog", "Large-scale engineering at Netflix"),
    "Cloudflare": ("Official company blog", "Networking, security, edge computing, AI infra"),
    "Hugging Face": ("Official company blog", "Open models, datasets, tooling tutorials"),
    "Simon Willison": ("Expert blog", "Daily hands-on notes on LLMs and AI tools"),
    "Latent Space": ("Newsletter / podcast", "AI engineering, agents, interviews with builders"),
    "Import AI": ("Newsletter", "Jack Clark's weekly AI research and policy digest"),
    "Interconnects": ("Newsletter", "Nathan Lambert on open models, RLHF, post-training"),
    "Ahead of AI": ("Newsletter", "Sebastian Raschka on LLM research papers"),
    "Google Research": ("Research lab blog", "Google Research papers explained"),
    "Microsoft Research": ("Research lab blog", "Microsoft Research news and papers"),
    "BAIR Blog": ("Research lab blog", "Berkeley AI Research (posts rarely)"),
    "LangChain": ("Official company blog", "Agent frameworks, LangGraph"),
    "The Decoder": ("News site", "Daily AI news"),
    "MarkTechPost": ("News site", "AI research news and paper summaries"),
    "VentureBeat AI": ("News site", "Enterprise AI business news"),
    "InfoQ": ("News site", "Software architecture, DevOps, practices, conference talks"),
    "Martin Fowler": ("Expert blog", "Software design, refactoring, architecture"),
    "The Pragmatic Engineer": ("Newsletter", "Gergely Orosz on the software industry and teams"),
    "GitHub Blog": ("Official company blog", "GitHub, Copilot, open source, dev tooling"),
    "Stack Overflow Blog": ("Official company blog", "Developer trends, surveys, engineering"),
    "IEEE Spectrum Computing": ("Magazine", "IEEE coverage of computing and software"),
    "ACM Queue": ("Magazine", "ACM practitioner articles"),
    "LWN.net": ("News site", "Linux kernel and open-source development"),
    "arXiv: LLM agents": ("Paper feed (arXiv search)", "New papers mentioning agentic / LLM agents / multi-agent systems"),
    "arXiv: AI for SE": ("Paper feed (arXiv search)", "New cs.SE papers about LLMs or agents"),
    "arXiv: Green AI / energy": ("Paper feed (arXiv search)", "New papers on energy / carbon of LLMs and software"),
    "arXiv: Uncertainty in LLMs": ("Paper feed (arXiv search)", "New papers on uncertainty in LLMs and agents"),
    "arXiv cs.SE (all new)": ("Paper feed (arXiv)", "Every new software engineering paper (~100/day)"),
    "Carbon Brief": ("News site", "Climate science and policy, data-driven"),
    "Canary Media": ("News site", "Clean energy transition"),
    "CleanTechnica": ("News site", "EVs, solar, clean tech (high volume)"),
    "Electrek": ("News site", "EVs and electric transport (high volume)"),
    "Grist": ("News site", "Climate and environmental justice"),
    "Inside Climate News": ("News site", "Investigative climate journalism"),
    "MIT Tech Review: Climate": ("News site", "Climate tech from MIT Technology Review"),
    "DatacenterDynamics": ("News site", "Data centres: power, cooling, energy use of AI"),
    "Krebs on Security": ("Expert blog", "Investigative cybercrime reporting"),
    "BleepingComputer": ("News site", "Malware, breaches, vulnerabilities"),
    "Schneier on Security": ("Expert blog", "Bruce Schneier on security and policy"),
    "The Hacker News": ("News site", "Daily cybersecurity news"),
    "Tom's Hardware": ("News site", "PC hardware, CPUs, GPUs (high volume)"),
    "IEEE Spectrum Semiconductors": ("Magazine", "Chip technology and fabrication"),
    "ServeTheHome": ("News site", "Servers, data-centre and AI hardware"),
}
VIDEO = {
    "MKBHD": "Phone and gadget reviews",
    "Linus Tech Tips": "PC hardware, gadgets",
    "The Verge": "Gadget reviews and tech explainers",
    "Dave2D": "Laptop and gadget reviews",
    "Fireship": "Fast programming and dev-news videos",
    "Two Minute Papers": "AI and graphics research explained",
    "Yannic Kilcher": "ML paper walkthroughs",
    "AI Explained": "Frontier AI model news and analysis",
    "Andrej Karpathy": "Deep LLM tutorials (posts rarely)",
    "Machine Learning Street Talk": "Long-form AI research interviews",
    "Computerphile": "Computer science concepts explained",
    "GOTO Conferences": "Software engineering conference talks",
    "Google for Developers": "Google's official developer channel",
    "Microsoft Developer": "Microsoft's official developer channel",
    "NVIDIA": "NVIDIA's official channel",
    "Apple": "Apple's official channel (events, ads)",
    "Lex Fridman": "Long interviews with tech and AI people",
    "Undecided with Matt Ferrell": "Clean energy and sustainable tech",
    "Climate Town": "Climate explained with humour",
}

cfg = json.load(open("feeds.json"))
check = {(r["category"], r["name"]): r for r in json.load(open("feed_check.json"))}

F = "Arial"
thin = Side(style="thin", color="D0D0D0")
border = Border(bottom=thin)
head_fill = PatternFill("solid", fgColor="1F3A5F")
input_fill = PatternFill("solid", fgColor="FFF2CC")

wb = Workbook()
ws = wb.active
ws.title = "Sources"

ws["A1"] = "Tech Pulse: candidate sources"
ws["A1"].font = Font(name=F, size=14, bold=True)
ws["A2"] = ("How to use: in the yellow 'Include?' column, choose Yes or No for each source. "
            "Add your own sources at the bottom (any site with an RSS feed, or any YouTube channel). "
            "Every feed was tested on " + datetime.now().strftime("%d %b %Y") + ".")
ws["A2"].font = Font(name=F, size=10, italic=True)
ws.merge_cells("A2:I2")
ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
ws.row_dimensions[2].height = 30

headers = ["Include?", "Section", "Source", "Type", "What it covers", "Feed works?",
           "Latest post", "Posts in last 7 days", "Feed URL"]
HR = 4
for i, h in enumerate(headers, 1):
    c = ws.cell(HR, i, h)
    c.font = Font(name=F, bold=True, color="FFFFFF")
    c.fill = head_fill
    c.alignment = Alignment(vertical="center", wrap_text=True)
ws.cell(HR, 8).comment = Comment(
    "Counted from the items the feed currently shows. Feeds that show only their newest "
    "10-20 items cap this number, so a big site can post more than shown.", "Tech Pulse")

r = HR + 1
for cat in cfg["categories"]:
    for f in cat["feeds"]:
        chk = check[(cat["name"], f["name"])]
        if cat["id"] == "videos":
            typ, what = "YouTube channel", VIDEO[f["name"]]
        else:
            typ, what = INFO[f["name"]]
        latest = datetime.fromisoformat(chk["latest"]).date() if chk["latest"] else None
        works = "Yes" if chk["ok"] else "No: " + ("feed removed (HTTP 410)" if chk["http"] == 410 else "feed is broken")
        yt_down = not chk["ok"] and "youtube.com" in chk["url"] and "404" in chk["error"]
        if yt_down:      # YouTube drops its feeds for hours at a time; that says nothing about the channel
            works = "Not checked: YouTube feeds were down during this check"
        vals = ["Yes" if chk["ok"] or yt_down else "No", cat["name"], f["name"], typ, what, works,
                latest, chk["last7d"] if chk["ok"] else None, chk["url"]]
        for i, v in enumerate(vals, 1):
            c = ws.cell(r, i, v)
            c.font = Font(name=F, size=10)
            c.border = border
            c.alignment = Alignment(vertical="top", wrap_text=i in (5,))
        ws.cell(r, 1).fill = input_fill
        ws.cell(r, 1).alignment = Alignment(horizontal="center", vertical="top")
        ws.cell(r, 7).number_format = "dd mmm yyyy"
        ws.cell(r, 9).font = Font(name=F, size=9, color="666666")
        r += 1
last = r - 1

# Blank rows for the user's own additions.
for k in range(10):
    rr = r + k
    ws.cell(rr, 1).fill = input_fill
    for i in range(1, 10):
        ws.cell(rr, i).font = Font(name=F, size=10)
ws.cell(r, 3, "(add your own here)").font = Font(name=F, size=10, italic=True, color="999999")
end = r + 9

dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
ws.add_data_validation(dv)
dv.add(f"A{HR+1}:A{end}")

# Grey out rows marked No; red text for broken feeds.
ws.conditional_formatting.add(f"A{HR+1}:I{end}", FormulaRule(
    formula=[f'$A{HR+1}="No"'], font=Font(color="A0A0A0")))
ws.conditional_formatting.add(f"F{HR+1}:F{end}", FormulaRule(
    formula=[f'LEFT($F{HR+1},2)="No"'], font=Font(color="C00000", bold=True)))

for col, w in zip("ABCDEFGHI", [10, 20, 28, 24, 52, 24, 13, 12, 60]):
    ws.column_dimensions[col].width = w
ws.freeze_panes = f"D{HR+1}"
ws.auto_filter.ref = f"A{HR}:I{end}"

# Summary sheet: live counts of what's chosen.
sm = wb.create_sheet("Summary")
sm["A1"] = "What you've chosen"
sm["A1"].font = Font(name=F, size=14, bold=True)
sm["A2"] = "Updates automatically as you change Yes/No on the Sources sheet."
sm["A2"].font = Font(name=F, size=10, italic=True)
for i, h in enumerate(["Section", "Sources available", "Sources chosen"], 1):
    c = sm.cell(4, i, h)
    c.font = Font(name=F, bold=True, color="FFFFFF")
    c.fill = head_fill
row = 5
for cat in cfg["categories"]:
    sm.cell(row, 1, cat["name"]).font = Font(name=F)
    sm.cell(row, 2, f'=COUNTIF(Sources!$B${HR+1}:$B${end},A{row})').font = Font(name=F)
    sm.cell(row, 3, f'=COUNTIFS(Sources!$B${HR+1}:$B${end},A{row},Sources!$A${HR+1}:$A${end},"Yes")').font = Font(name=F)
    row += 1
sm.cell(row, 1, "Total").font = Font(name=F, bold=True)
sm.cell(row, 2, f"=SUM(B5:B{row-1})").font = Font(name=F, bold=True)
sm.cell(row, 3, f"=SUM(C5:C{row-1})").font = Font(name=F, bold=True)
sm.column_dimensions["A"].width = 24
sm.column_dimensions["B"].width = 18
sm.column_dimensions["C"].width = 16

notes = [
    "Notes",
    "Anthropic, Meta AI (ai.meta.com) and The Batch (DeepLearning.AI) publish no RSS feed, so they can't be followed automatically. Their stories still show up through Techmeme, The Verge, The Decoder and others.",
    "arXiv searches are tuned to your research (agents, AI for SE, LLM energy, uncertainty). Tell me other keywords and I'll add them.",
    "Any YouTube channel can be added: give me the channel link.",
    "The site updates itself every hour: new posts from every chosen source appear on their own.",
]
for k, t in enumerate(notes):
    c = sm.cell(row + 3 + k, 1, t)
    c.font = Font(name=F, size=10, bold=(k == 0))
    sm.merge_cells(start_row=row + 3 + k, start_column=1, end_row=row + 3 + k, end_column=6)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    if k:
        sm.row_dimensions[row + 3 + k].height = 28
for col in "DEF":
    sm.column_dimensions[col].width = 22

# Paper venues sheet: conferences, journals and topic searches from papers.json.
pcfg = json.load(open("papers.json"))
pidx = json.load(open("site/data/papers/index.json"))
fname = {f["id"]: f["name"] for f in pcfg["fields"]}
pv = wb.create_sheet("Paper venues", 1)
pv["A1"] = "Tech Pulse: research paper sources"
pv["A1"].font = Font(name=F, size=14, bold=True)
pv["A2"] = ("Conferences: papers whose authors note on arXiv that they were accepted there (this year and next). "
            "Journals: newest 60 articles with abstracts (OpenAlex). Topics: newest arXiv papers matching a search. "
            "Counts are from " + datetime.now().strftime("%d %b %Y") + ". Set Include? to Yes or No; add venues in the blank rows.")
pv["A2"].font = Font(name=F, size=10, italic=True)
pv["A2"].alignment = Alignment(wrap_text=True, vertical="top")
pv.merge_cells("A2:G2")
pv.row_dimensions[2].height = 44
ph = ["Include?", "Kind", "Field", "Venue", "Full name / search", "Papers found now", "Where the papers come from"]
for i, h in enumerate(ph, 1):
    c = pv.cell(4, i, h)
    c.font = Font(name=F, bold=True, color="FFFFFF")
    c.fill = head_fill
counts = {}
for c in pidx["conferences"]:
    counts.setdefault(c["id"], []).append(f"{c['year']}: {c['count']}")
jcount = {j["id"]: j["count"] for j in pidx["journals"]}
tcount = {t["id"]: t["count"] for t in pidx["topics"]}
prow = 5
rows = ([("Conference", fname[v["field"]], v["id"], v["name"], ", ".join(counts.get(v["id"], ["0"])), "arXiv author notes + official program link") for v in pcfg["conferences"]]
        + [("Journal", fname[j["field"]], j["id"], j["name"], jcount.get(j["id"], 0), f"OpenAlex, ISSN {j['issn']}") for j in pcfg["journals"]]
        + [("Topic search", "", t["name"], t["query"], f"{tcount.get(t['id'], 0)} in last 10 days", "arXiv search") for t in pcfg["topics"]])
for vals in rows:
    for i, v in enumerate(("Yes",) + vals, 1):
        c = pv.cell(prow, i, v)
        c.font = Font(name=F, size=10)
        c.border = border
        c.alignment = Alignment(vertical="top", wrap_text=i == 5)
    pv.cell(prow, 1).fill = input_fill
    pv.cell(prow, 1).alignment = Alignment(horizontal="center", vertical="top")
    prow += 1
for k in range(8):
    pv.cell(prow + k, 1).fill = input_fill
pv.cell(prow, 4, "(add your own here)").font = Font(name=F, size=10, italic=True, color="999999")
pdv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
pv.add_data_validation(pdv)
pdv.add(f"A5:A{prow + 7}")
pv.conditional_formatting.add(f"A5:G{prow + 7}", FormulaRule(formula=['$A5="No"'], font=Font(color="A0A0A0")))
for col, w in zip("ABCDEFG", [10, 14, 22, 16, 52, 22, 40]):
    pv.column_dimensions[col].width = w
pv.freeze_panes = "E5"
pv.auto_filter.ref = f"A4:G{prow + 7}"

from openpyxl.workbook.properties import CalcProperties
wb.calculation = CalcProperties(fullCalcOnLoad=True)
wb.save("Tech-Pulse-Sources.xlsx")
print("rows", last - HR, "end", end)
