from __future__ import annotations

from decimal import Decimal


def evaluate_rolling_windows(points: list[dict]) -> list[dict]:
    """Evaluate each five-input window against the following manual point."""
    results=[]
    for start in range(max(0,len(points)-5)):
        inputs=points[start:start+5]
        outcome=points[start+5]
        a=Decimal(inputs[3]["price"]); b=Decimal(inputs[4]["price"]); leg=b-a
        targets={"COP":b-leg*Decimal("0.618"),"OP":b-leg,"XOP":b-leg*Decimal("1.618")}
        manual=Decimal(outcome["price"])
        distances={name:abs(manual-price) for name,price in targets.items()}
        percentages={name:(distance/abs(target)*Decimal(100) if target else Decimal("Infinity"))
                     for (name,distance),target in zip(distances.items(),targets.values())}
        nearest=min(distances,key=distances.get)
        results.append({
            "window_index":start,"window_label":f"P{start}..P{start+4}",
            "input_indices":list(range(start,start+5)),"manual_next_index":start+5,
            "manual_next_price":str(manual),"direction":"DOWN" if leg>0 else "UP",
            "cop_price":str(targets["COP"]),"op_price":str(targets["OP"]),"xop_price":str(targets["XOP"]),
            **{f"abs_distance_to_{name.lower()}":str(value) for name,value in distances.items()},
            **{f"percent_distance_to_{name.lower()}":str(value) for name,value in percentages.items()},
            "nearest_objective":nearest,"nearest_error_pct":str(percentages[nearest]),
        })
    return results
