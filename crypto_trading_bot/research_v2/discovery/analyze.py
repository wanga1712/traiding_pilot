from __future__ import annotations

import csv, hashlib, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path

RATIOS={"0.618":0.618,"1.000":1.0,"1.618":1.618}


def _sign(value): return 1 if value>0 else -1 if value<0 else 0
def _quantile(values,q):
    ordered=sorted(values); position=(len(ordered)-1)*q; lower=math.floor(position); upper=math.ceil(position)
    return ordered[lower] if lower==upper else ordered[lower]*(upper-position)+ordered[upper]*(position-lower)
def _pearson(a,b):
    ma,mb=statistics.mean(a),statistics.mean(b); numerator=sum((x-ma)*(y-mb) for x,y in zip(a,b))
    denominator=math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
    return numerator/denominator if denominator else 0.0
def _ranks(values):
    order=sorted(range(len(values)),key=values.__getitem__); ranks=[0.0]*len(values); index=0
    while index<len(order):
        end=index
        while end+1<len(order) and values[order[end+1]]==values[order[index]]: end+=1
        rank=(index+end)/2+1
        for offset in range(index,end+1): ranks[order[offset]]=rank
        index=end+1
    return ranks
def _kmeans_1d(values,k):
    centers=[_quantile(values,(i+.5)/k) for i in range(k)]
    for _ in range(100):
        labels=[min(range(k),key=lambda j:abs(value-centers[j])) for value in values]
        updated=[statistics.mean([v for v,label in zip(values,labels) if label==j]) if any(label==j for label in labels) else centers[j] for j in range(k)]
        if max(abs(a-b) for a,b in zip(centers,updated))<1e-12: break
        centers=updated
    ordered=sorted(range(k),key=centers.__getitem__); remap={old:new for new,old in enumerate(ordered)}
    return [centers[i] for i in ordered],[remap[label] for label in labels]
def _silhouette_1d(values,labels):
    scores=[]
    for i,value in enumerate(values):
        same=[abs(value-other) for j,other in enumerate(values) if labels[j]==labels[i] and j!=i]
        a=statistics.mean(same) if same else 0
        other_clusters=set(labels)-{labels[i]}; b=min(statistics.mean([abs(value-values[j]) for j in range(len(values)) if labels[j]==cluster]) for cluster in other_clusters)
        scores.append((b-a)/max(a,b) if max(a,b) else 0)
    return statistics.mean(scores)


def analyze_annotation(input_csv: Path, output_dir: Path, annotation_id: str) -> dict:
    rows=list(csv.DictReader(input_csv.open(encoding="utf-8")))
    if len(rows)!=42 or [int(row["point_index"]) for row in rows]!=list(range(42)):
        raise ValueError("expected immutable contiguous P0..P41")
    points=[{"index":int(row["point_index"]),"timestamp":datetime.fromisoformat(row["timestamp"]),"price":float(row["price"])} for row in rows]
    observations=[]
    for i in range(5,42):
        p=points[i-5:i+1]; d=[p[j+1]["price"]-p[j]["price"] for j in range(4)]
        if any(value==0 for value in d): raise ValueError(f"zero price leg in window ending P{i}")
        next_delta=p[5]["price"]-p[4]["price"]; magnitude=abs(next_delta)/abs(d[3]); signed=next_delta/abs(d[3])
        times=[(p[j+1]["timestamp"]-p[j]["timestamp"]).total_seconds()/3600 for j in range(5)]
        if any(value<=0 for value in times): raise ValueError(f"non-positive duration in window ending P{i}")
        errors={name:abs(magnitude-ratio) for name,ratio in RATIOS.items()}; nearest=min(errors,key=errors.get)
        observation={"reference_point":f"P{i}","window":f"P{i-5}..P{i-1}",
            **{f"d{j+1}":d[j] for j in range(4)},"target_signed":signed,"target_magnitude":magnitude,
            "direction_expected":-_sign(d[3]),"direction_actual":_sign(next_delta),"direction_alternates":-_sign(d[3])==_sign(next_delta),
            "q2":abs(d[1])/abs(d[0]),"q3":abs(d[2])/abs(d[1]),"q4":abs(d[3])/abs(d[2]),
            "time_d1_hours":times[0],"time_d2_hours":times[1],"time_d3_hours":times[2],"time_d4_hours":times[3],"time_next_hours":times[4],
            "duration_ratio_next_to_d4":times[4]/times[3],"nearest_fixed_ratio":nearest,
            "nearest_ratio_abs_error":errors[nearest],"nearest_ratio_relative_error":errors[nearest]/RATIOS[nearest]}
        observations.append(observation)
    magnitudes=[row["target_magnitude"] for row in observations]; signed=[row["target_signed"] for row in observations]
    candidates=[]
    for k in (2,3,4):
        centers,labels=_kmeans_1d(magnitudes,k); candidates.append((k,_silhouette_1d(magnitudes,labels),centers,labels))
    best=max(candidates,key=lambda item:item[1]); _,silhouette,centers,labels=best
    for row,label in zip(observations,labels): row["natural_cluster"]=label
    relationships={}
    for feature in ("q2","q3","q4","duration_ratio_next_to_d4"):
        values=[row[feature] for row in observations]
        relationships[feature]={"pearson_r":_pearson(magnitudes,values),"spearman_rho":_pearson(_ranks(magnitudes),_ranks(values))}
    nearest_counts={name:sum(row["nearest_fixed_ratio"]==name for row in observations) for name in RATIOS}
    summary={"annotation_id":annotation_id,"point_count":len(points),"evaluable_windows":len(observations),
        "source_sha256":hashlib.sha256(input_csv.read_bytes()).hexdigest(),
        "direction_alternation_count":sum(row["direction_alternates"] for row in observations),
        "direction_alternation_rate":sum(row["direction_alternates"] for row in observations)/len(observations),
        "target_signed":_describe(signed),"target_magnitude":_describe(magnitudes),"nearest_ratio_counts":nearest_counts,
        "within_5_percent":sum(row["nearest_ratio_relative_error"]<=.05 for row in observations),
        "within_10_percent":sum(row["nearest_ratio_relative_error"]<=.10 for row in observations),
        "within_20_percent":sum(row["nearest_ratio_relative_error"]<=.20 for row in observations),
        "natural_clustering":{"method":"deterministic 1D k-means; k selected from 2..4 by silhouette","k":best[0],"silhouette":silhouette,"centers":centers},
        "relationships":relationships,"created_at":datetime.now(timezone.utc).isoformat()}
    output_dir.mkdir(parents=True,exist_ok=True)
    with (output_dir/"window_metrics.csv").open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(observations[0])); writer.writeheader(); writer.writerows(observations)
    (output_dir/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    (output_dir/"source_snapshot.csv").write_bytes(input_csv.read_bytes())
    _charts(observations,output_dir)
    return summary


def _describe(values):
    return {"mean":statistics.mean(values),"median":statistics.median(values),"std":statistics.stdev(values),"min":min(values),"max":max(values),
            "quantiles":{str(q):_quantile(values,q) for q in (.05,.10,.25,.50,.75,.90,.95)}}


def _charts(rows,output_dir):
    import plotly.graph_objects as go
    indices=list(range(5,42)); magnitude=[row["target_magnitude"] for row in rows]
    def save(name,figure):
        figure.update_layout(template="plotly_dark",width=1100,height=600); figure.write_html(output_dir/name,include_plotlyjs="cdn",full_html=True)
    save("01_target_signed_by_window.html",go.Figure(go.Scatter(x=indices,y=[r["target_signed"] for r in rows],mode="lines+markers")))
    save("02_target_magnitude_distribution.html",go.Figure(go.Histogram(x=magnitude,nbinsx=10)))
    save("03_target_magnitude_vs_q4.html",go.Figure(go.Scatter(x=[r["q4"] for r in rows],y=magnitude,mode="markers")))
    save("04_target_magnitude_vs_q3.html",go.Figure(go.Scatter(x=[r["q3"] for r in rows],y=magnitude,mode="markers")))
    save("05_target_magnitude_vs_duration_ratio.html",go.Figure(go.Scatter(x=[r["duration_ratio_next_to_d4"] for r in rows],y=magnitude,mode="markers")))
