# Evaluation Report

## Talk2Data (text-to-SQL accuracy)

Each question is answered by **Talk2Data** (LLM-generated read-only SQL); the answer is checked against the **ground truth** computed directly from the database.

**Accuracy: 10/10 (100%)**

| # | Question | Expected | Got | Result |
|---|---|---|---|---|
| 1 | What was the total revenue in May 2026? | 998088.0 | 998087.75 | ✅ |
| 2 | How many distinct product categories are there? | 5 | 5 | ✅ |
| 3 | How many distinct products are there? | 15 | 15 | ✅ |
| 4 | Which region had the highest total revenue in May 2026? | North America | North America | ✅ |
| 5 | Which region had the lowest total revenue in May 2026? | LATAM | LATAM | ✅ |
| 6 | What was the total revenue for the Online channel in May 2026? | 537455.0 | 537454.6 | ✅ |
| 7 | Which product generated the most revenue overall? | Wireless Earbuds | Wireless Earbuds | ✅ |
| 8 | What was the total gross profit in May 2026? | 377996.0 | 377995.95 | ✅ |
| 9 | How many units were sold in total in May 2026? | 22742 | 22742 | ✅ |
| 10 | What was the total revenue for the Beauty & Wellness category in May 2026? | 247990.0 | 247989.81 | ✅ |

## Report pipeline (figure grounding + structure)

Each report is generated end-to-end by the LangGraph pipeline, then every quoted $ / % figure is checked against the approved set recomputed from the database (including the title, key messages and recommendations, which the runtime verify node does not cover).

| Dataset | Report title | Unapproved figures | Structure | Result |
|---|---|---|---|---|
| sales | Revenue Growth and Channel Insights | none | all checks pass | ✅ |
| budget | May Financial Performance Review | none | all checks pass | ✅ |
