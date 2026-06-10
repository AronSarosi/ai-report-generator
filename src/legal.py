"""Plain-English Privacy Notice and Terms of Use shown in the app footer.

Kept honest and specific on purpose: the full dataset is never sent to the model (only the
schema + aggregated figures + a few sample values), uploads are processed transiently, and the
client IP plus usage counts are used only to enforce fair-use limits. This is a demo, not legal
advice, but it accurately describes how the app actually handles data.
"""

# Shown to visitors who hit the monthly limit, and in the policies below. Change freely.
CONTACT_EMAIL = "aron.sarosi13@gmail.com"

PRIVACY_MD = f"""
**Last updated: June 2026**

This is a **free demonstration application** built to showcase an AI report-generation system.
Please read how your data is handled before uploading anything.

**What we process**
- **Files you upload** (CSV / Excel / JSON, and an optional PowerPoint template). Used only to
  produce your report or answer your questions during your session.
- **Minimal technical metadata** (your IP address and counts of reports/questions), used solely
  to apply fair-use limits.

**How your data is used**
- Your file is loaded into a temporary database to compute the analytics. **Your full dataset is
  never sent to the AI model.** Only the data *structure* (column names/types), the *aggregated
  figures*, and a small number of sample values are sent to the language-model provider (OpenAI,
  or Azure OpenAI when configured) to write the narrative and generate SQL.
- The provider processes this under its own API data policy. OpenAI does **not** train its models
  on data submitted via the API and retains it only briefly for abuse monitoring. When configured
  for **Azure OpenAI**, this processing stays inside a private Azure tenant.
- When tracing is enabled, an **observability tool (Langfuse)** records the model calls (the same
  schema, aggregated figures and sample values described above, plus the generated text) so the
  system can be debugged and quality-checked. It is not used for advertising or profiling.

**Retention**
- Uploads are processed **transiently**: the original file is deleted immediately after it is
  loaded, and the working data is not added to any long-term store. On the hosted demo the
  underlying instance is ephemeral and its storage is wiped when it recycles.
- We do not build user profiles, and we do not sell or share your data with anyone other than the
  AI provider above (and error/observability tooling, when enabled, for debugging).

**Your responsibilities**
- Because this is a public demo, **please do not upload personal, confidential, regulated, or
  otherwise sensitive data.** Use the bundled sample data or non-sensitive data only.

Questions about privacy: {CONTACT_EMAIL}
"""

TERMS_MD = f"""
**Last updated: June 2026**

By using this free demonstration application ("the Demo"), you agree to the following.

**The Demo is provided "as is"**
- It is for **evaluation and demonstration only**, without warranties of any kind (including
  accuracy, fitness for a particular purpose, or availability).
- AI-generated output may contain errors. **Do not rely on it for financial, legal, or business
  decisions without independently verifying the figures.** Figures are computed from your data and
  checked against it, but you remain responsible for validating anything you use.

**Fair use**
- To keep the Demo free and available, usage is limited to **5 reports and 50 questions per user
  per calendar month**, **25 MB per uploaded file**, and an overall daily capacity shared across
  all visitors.
- Please don't try to circumvent these limits, overload the service, upload malicious files, or
  use the Demo for unlawful purposes. Want more, or a version built for your team? Get in touch.

**Your content**
- You keep all rights to the data you upload, and you're responsible for having the right to
  upload it and for ensuring it contains no sensitive or personal data (see the Privacy Notice).
- The Demo's code and design remain the property of its author.

**Limitation of liability**
- To the maximum extent permitted by law, the author is not liable for any damages arising from
  your use of the Demo, including any loss arising from reliance on its output.

Contact: {CONTACT_EMAIL}
"""
