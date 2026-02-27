# Agentic AI DeepMind

# Evidence Grading for Aging Interventions

- **Objective:** Build an agentic system using the Gemini API (for orchestration and planning) and MedGemma (for medical reasoning) that retrieves, classifies, and synthesises scientific information on ageing interventions.
- **Deliverable:** A working demo. Given an intervention name (e.g., "rapamycin," "NAD+ precursors), your agent must return a structured evidence report with a transparent confidence score.

# Challenge Goal

Ageing research is growing rapidly. Billions are being invested in longevity startups, supplements are marketed as "anti-ageing," and social media often amplifies preliminary findings as major breakthroughs. This makes it extremely difficult, even for scientists, to differentiate interventions backed by rigorous clinical evidence from those supported only by cell culture or animal studies.

Build an AI agent that, given any ageing-related intervention, automatically retrieves literature, and possibly information from additional databases, classifies studies by evidence level, identifies gaps in the evidence hierarchy, and outputs a calibrated confidence score with a human-readable report.

Your agent should be able to handle interventions ranging from well-studied compounds (metformin, rapamycin) to emerging claims (NMN supplements, hyperbaric oxygen, epigenetic reprogramming).

# Why This Matters

The longevity sector has a due-diligence problem. Over $5.2B in venture capital flowed into longevity biotech between 2021 and 2024, funding companies like Altos Labs ($3B), NewLimit, Retro Biosciences, and dozens more. Yet investors, pharma partners, and even the companies themselves struggle to objectively assess how strong the evidence really is behind a given ageing target. Today, that assessment is done manually, a systematic review costs a lot, takes months, and is outdated by the time it's published. VCs and biotech analysts routinely pay six figures for consultant-led pipeline due diligence that still boils down to a handful of experts reading papers. An automated evidence-grading agent could compress this into minutes and, more importantly, make the reasoning transparent and reproducible.

# Useful Resources

## Evidence Hierarchy

| **Level** | **Study Type** | **Example** | **Weight** |
| --- | --- | --- | --- |
| **1** | Systematic reviews & meta-analyses | Cochrane review of rapamycin in ageing | Highest |
| **2** | Randomised controlled trials (RCTs) | Phase 2 trial of metformin (TAME) | High |
| **3** | Observational / epidemiological studies | Cohort study linking metformin to reduced mortality | Moderate |
| **4** | Animal model studies (in vivo) | Rapamycin extending lifespan in mice (ITP) | Lower |
| **5** | Cell culture / in vitro studies | Senolytics clearing senescent cells in culture | Low |
| **6** | In silico / computational predictions | Network pharmacology predicting drug targets | Lowest |

A compound supported only by Level 5–6 evidence should receive a very different confidence score than one with Level 1–2 evidence.

## Example Interventions to Test

| **Intervention** | **Expected Evidence Profile** |
| --- | --- |
| **Rapamycin / mTOR inhibitors** | Strong animal data (ITP), emerging human trials |
| **Metformin (TAME trial)** | Epidemiological + ongoing RCT |
| **NAD+ precursors (NMN/NR)** | Animal data + mixed human results |
| **Senolytics (dasatinib + quercetin)** | Strong preclinical, early human |
| **Young plasma / parabiosis** | Animal data + one controversial company |
| **Hyperbaric oxygen therapy** | Small trials, media hype |
| **Epigenetic reprogramming (Yamanaka factors)** | Mostly in vitro/animal |

## Useful Data Sources

- https://pubmed.ncbi.nlm.nih.gov/
- https://clinicaltrials.gov/
- https://genomics.senescence.info/

## Longevity Context

For teams new to ageing research, good starting points include the NIA Interventions Testing Program (ITP) and the Hallmarks of Aging framework (López-Otín et al., 2023). Understanding the landscape will help you design a smarter retrieval strategy.

## Technical Details

- You have been assigned a personal Gmail Account with free credits to use the Gemini API
- Tutorial on how to claim credits and activate your Gemini API Key: https://www.youtube.com/watch?v=4t5G4CrQcSw
- Link to claim credits (first watch video): https://trygcp.dev/claim/bio-ai

# Berlin Bio x AI Hackathon
The Berlin Bio × AI Hackathon is happening Feb 27-28. 24 hours for scientific and computational people to build something together at the intersection of bio and AI. Three tracks: protein design, genome modeling & synthesis, and agentic AI in life sciences.

event
{
"start_at": "27 Feb 2026, 3:00 pm",
"end_at": "28 Feb 2026, 4:00 pm"
}

## About This Event
See you soon, builders!
👤 Action Required: Finish your profile and form teams! Please try to join teams before 12:00 on Friday.
To make sure we hit the ground running, we want everyone to start connecting and finalizing their teams now! Please complete your profile and start reaching out to fellow participants in your track to set up your teams before the start of the event. Teams can be a maximum of 5 people and a minimum of 3 (and we'll need to make sure we have a maximum of 7 teams per track due to compute constraints).

If you're having trouble: make sure you leave your existing team (if you're in one) before you request to join another team.

We heard from some people that BuilderBase was having some issues with messaging being buggy on the platform - sorry about this! We've created a WhatsApp community that we can use throughout the event, and you're welcome to join already: https://chat.whatsapp.com/JQqrIGzhU4J9EiQiz8a4Z0

Keep in mind there is a public transport strike (across all of Germany) on Fri and Saturday (very annoying timing). Luckily, S Bahn trains will still be running, and the venue NLND is reachable via S Bahn, via S Sonnenallee (Ring) or S Köllnische Heide.

Here's a one route you could take from Berlin Hauptbahnhof tomorrow; here's another route. Here's a route you could take from the airport.

As your compute platform, you'll be using Lyceum

🛠️ Accessing Compute & GPU Credits
To power your projects, we are providing access to specialized hardware and high-performance infrastructure via Lyceum. Follow the steps below to get started:

Lyceum (Virtual Machines & GPU)
Use Lyceum to provision VM instances and manage your own computational workflows.

Login: Use the Email + Password provided to your team beforehand at the Lyceum Dashboard.
Set-up: Log into the dashboard where you can either use their API to send jobs for GPU execution or set up dedicated VMs.
Documentation: For technical implementation details and API references, refer to the Lyceum Docs.
Resource Management: Please ensure you shut down instances when they are not actively in use to conserve your team's credit allocation throughout the hackathon.
For questions and technical support with the compute platform during the hack: max@lyceum.technology

Any general questions or need help? Email hannah.p@nucleate.org or message Hannah on Whatsapp

🛠️ Accessing Compute & GPU Credits
To power your projects, we are providing access to specialized hardware and high-performance infrastructure via Lyceum. Follow the steps below to get started:

Lyceum (Virtual Machines & GPU)
Use Lyceum to provision VM instances and manage your own computational workflows.

Login: Use the Email + Password provided to your team beforehand at the Lyceum Dashboard.
Set-up: Log into the dashboard where you can either use their API to send jobs for GPU execution or set up dedicated VMs.
Documentation: For technical implementation details and API references, refer to the Lyceum Docs.
Resource Management: Please ensure you shut down instances when they are not actively in use to conserve your team's credit allocation throughout the hackathon.
For questions and technical support with the compute platform during the hack: max@lyceum.technology Any general questions or need help? Email hannah.p@nucleate.org or message Hannah on WhatsApp.

🌍 The Translational Mentality: From Code to Impact
Building impressive tech is only half the battle. To win, teams must adopt a translational mentality: the ability to bridge the gap between a technical breakthrough and its real-world application in life sciences.

⚖️ Beyond the Tech
Pitches will not be judged solely on code complexity or agent architecture. Judges are looking for context: you must demonstrate not just how your tool works, but why it matters.

🎯 Things to Keep in Mind
Problem-Solution Fit: Are you solving a specific bottleneck in life sciences, or just building a "cool" tool in search of a problem?
Stakeholder Awareness: Who is the end-user? Your project should reflect the specific needs of a lab technician, researcher, clinician, or patient population.
Scalability: How does this move from a hackathon prototype into a real-world drug discovery or diagnostic pipeline?
[!TIP] The "So What?" Test Ask yourselves: "If this existed today, how would it change a scientist's, a clinician's or a patient's daily life?" If you can answer that clearly, you have a translational project.

Build for the world, not just the terminal.

