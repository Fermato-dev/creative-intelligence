"""Kill / Scale / Iterate rule engine — v2 with CVR, fatigue, clickbait detection."""

from .config import TARGET_CPA, TARGET_ROAS, MIN_SPEND_FOR_DECISION, MIN_IMPRESSIONS


def evaluate_creative(m, target_cpa=None, target_roas=None,
                      min_spend=None, min_impressions=None):
    """Evaluate single ad and return list of (ACTION, reason, detail) tuples.

    Actions: KILL, SCALE, ITERATE, WATCH, OK, INFO
    """
    target_cpa = target_cpa if target_cpa is not None else TARGET_CPA
    target_roas = target_roas if target_roas is not None else TARGET_ROAS
    min_spend = min_spend if min_spend is not None else MIN_SPEND_FOR_DECISION
    min_impressions = min_impressions if min_impressions is not None else MIN_IMPRESSIONS

    recommendations = []
    spend = m["spend"]
    impressions = m["impressions"]

    if spend < min_spend and impressions < min_impressions:
        return [("INFO", "Nedostatek dat pro rozhodnuti", f"Spend {spend} CZK, {impressions} impr")]

    # ── KILL ──

    if m["cpa"] and m["cpa"] > target_cpa * 2 and spend > min_spend:
        recommendations.append(("KILL", "CPA 2x+ nad targetem",
            f"CPA {m['cpa']} CZK vs target {target_cpa} CZK"))
    elif m["cpa"] and m["cpa"] > target_cpa * 1.3 and spend > min_spend * 2:
        recommendations.append(("KILL", "CPA 30%+ nad targetem pri vyssim spendu",
            f"CPA {m['cpa']} CZK vs target {target_cpa} CZK, spend {spend} CZK"))

    # Multi-signal fatigue
    if m["frequency"] > 5.0 and m["ctr"] < 1.0:
        recommendations.append(("KILL", "Extremni ad fatigue — okamzite zastavit",
            f"Frekvence {m['frequency']} (>5), CTR {m['ctr']}%"))
    elif m["frequency"] > 3.0 and m["ctr"] < 0.8:
        recommendations.append(("KILL", "Ad fatigue — vysoka frekvence + nizky CTR",
            f"Frekvence {m['frequency']}, CTR {m['ctr']}%"))
    elif m["frequency"] > 2.5 and m.get("cvr") is not None and m["cvr"] < 1.0 and m["ctr"] > 1.0:
        recommendations.append(("KILL", "Skryta fatigue — CTR OK ale CVR pada",
            f"Freq {m['frequency']}, CTR {m['ctr']}% ale CVR jen {m['cvr']}%"))

    if spend > target_cpa * 3 and m["purchases"] == 0:
        recommendations.append(("KILL", "Zadne nakupy pri vysokem spendu",
            f"Spend {spend} CZK, 0 purchases"))

    if m["roas"] is not None and m["roas"] < 1.0 and spend > min_spend:
        recommendations.append(("KILL", "ROAS pod 1.0 — ztratovy", f"ROAS {m['roas']}"))

    if m["ctr"] > 2.0 and m.get("cvr") is not None and m["cvr"] < 0.5 and spend > min_spend * 2:
        recommendations.append(("KILL", "Clickbait kreativa — vysoky CTR, nulova konverze",
            f"CTR {m['ctr']}% ale CVR {m['cvr']}%"))

    # ── SCALE ──

    confidence = m.get("confidence", 0)

    if m["roas"] and m["roas"] > target_roas * 1.2 and spend > min_spend:
        if confidence >= 0.5:
            recommendations.append(("SCALE", "ROAS 20%+ nad targetem",
                f"ROAS {m['roas']} vs target {target_roas}, {m['purchases']} nakupu"))
        else:
            recommendations.append(("WATCH", "Slibny ROAS ale malo dat",
                f"ROAS {m['roas']}, jen {m['purchases']} nakupu"))

    if m["cpa"] and m["cpa"] < target_cpa * 0.7 and m["purchases"] >= 5:
        recommendations.append(("SCALE", "CPA 30%+ pod targetem s dostatkem konverzi",
            f"CPA {m['cpa']} CZK, {m['purchases']} nakupu"))

    if m.get("cvr") and m["cvr"] > 3.0 and m["purchases"] >= 5 and confidence >= 0.5:
        recommendations.append(("SCALE", "Vysoka konverzni mira — kreativa prodava",
            f"CVR {m['cvr']}% (benchmark >2%), {m['purchases']} nakupu"))

    # ── ITERATE — VIDEO ──

    if m["is_video"] and m["hook_rate"] is not None:
        if m["hook_rate"] >= 30 and m["hold_rate"] is not None and m["hold_rate"] < 40:
            recommendations.append(("ITERATE", "Dobry hook, slaby hold — uprav stred videa",
                f"Hook {m['hook_rate']}% (OK), Hold {m['hold_rate']}% (benchmark >40%)"))
        elif m["hook_rate"] >= 25 and m["hold_rate"] is not None and m["hold_rate"] < 30:
            recommendations.append(("ITERATE", "Solidni hook, slaby hold",
                f"Hook {m['hook_rate']}%, Hold {m['hold_rate']}%"))

        if m["hook_rate"] < 25 and m["roas"] and m["roas"] > target_roas * 0.8:
            recommendations.append(("ITERATE", "Podprumerny hook ale slusny ROAS — natoc novy hook",
                f"Hook {m['hook_rate']}% (benchmark >=25%), ROAS {m['roas']}"))

        if m["hook_rate"] >= 35 and confidence >= 0.5:
            recommendations.append(("SCALE", "Vynikajici hook rate",
                f"Hook {m['hook_rate']}% (elite >35%)"))

        if m["hook_rate"] < 20 and impressions > min_impressions:
            recommendations.append(("ITERATE", "Nizky hook — 1. frame a text overlay nefunguje",
                f"Hook {m['hook_rate']}% (benchmark >=25%, minimum 20%)"))

        dropoff = m.get("video_dropoff")
        if dropoff == "SPATNY_HOOK":
            recommendations.append(("ITERATE", "Video drop-off: spatny opening",
                f"Hook {m['hook_rate']}% — zmen 1. frame"))
        elif dropoff == "MIDDLE_SAG":
            recommendations.append(("ITERATE", "Video drop-off: propad uprostred",
                f"Silny drop mezi 25-50% videa"))
        elif dropoff == "POZDNI_CTA":
            recommendations.append(("ITERATE", "Video drop-off: CTA prilis pozde",
                f"75% retention OK ale 100% propad — presun CTA drive"))

    # ── ITERATE — STATIC ──

    if not m["is_video"]:
        if m["ctr"] < 1.0 and impressions > min_impressions and spend > min_spend:
            recommendations.append(("ITERATE", "Nizky CTR — zmen vizual nebo text",
                f"CTR {m['ctr']}% (benchmark food&bev >1.5%)"))

        if m["ctr"] > 2.0 and m["roas"] and m["roas"] < target_roas * 0.6 and spend > min_spend:
            detail = f"CTR {m['ctr']}%, ROAS {m['roas']}"
            if m.get("cvr") is not None:
                detail += f", CVR {m['cvr']}%"
            recommendations.append(("ITERATE", "Vysoky CTR ale nizky ROAS — disconnect kreativa vs. LP", detail))

        if m.get("cvr") is not None and m["cvr"] < 1.0 and m["ctr"] > 1.5 and spend > min_spend:
            recommendations.append(("ITERATE", "LP problem — CTR OK ale CVR nizka",
                f"CTR {m['ctr']}%, CVR {m['cvr']}%"))

        if m["ctr"] > 2.0 and m["roas"] and m["roas"] > target_roas and confidence >= 0.5:
            recommendations.append(("SCALE", "Silny CTR + ROAS",
                f"CTR {m['ctr']}%, ROAS {m['roas']}"))

        if m.get("cvr") and m["cvr"] > 3.0 and m["roas"] and m["roas"] > target_roas * 0.9 and confidence >= 0.4:
            recommendations.append(("SCALE", "Vysoka CVR — banner ktery konvertuje",
                f"CVR {m['cvr']}%, ROAS {m['roas']}"))

    # ── WATCH ──

    if m["frequency"] > 2.0 and m["frequency"] <= 3.0:
        typ = "videa" if m["is_video"] else "banneru"
        recommendations.append(("WATCH", f"Frekvence {typ} roste — priprav refresh kreativy",
            f"Frekvence {m['frequency']} (alert na 3.0 cold / 6.0 retargeting)"))
    elif m["frequency"] > 3.0 and m["frequency"] <= 5.0 and m["ctr"] >= 0.8:
        recommendations.append(("WATCH", "Vysoka frekvence, CTR jeste drzi — casovana bomba",
            f"Freq {m['frequency']}, CTR {m['ctr']}% — refresh do 7 dni"))

    if not recommendations:
        if m["roas"] and m["roas"] >= target_roas * 0.8:
            cvr_info = f", CVR {m['cvr']}%" if m.get("cvr") else ""
            recommendations.append(("OK", "V norme", f"ROAS {m['roas']}, CPA {m['cpa']}{cvr_info}"))
        else:
            recommendations.append(("WATCH", "Bez jasneho signalu", "Sleduj dalsi dny"))

    return recommendations
