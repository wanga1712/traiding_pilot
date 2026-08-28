from __future__ import annotations

import argparse, json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html, no_update
from plotly.subplots import make_subplots

from crypto_trading_bot.geometry_v2 import (
    GeometryPoint, GeometryValidationError, GeometryWindow, PointSource,
    RollingObjectiveCalculatorV2,
)
from .dma import DMA_SPECS, displaced_moving_average, dma_state

ROLES = ("A0", "B0", "C0", "A1", "B1")
COLORS = {"COP":"#f5a623", "OP":"#ff4d8d", "XOP":"#9b59b6"}


def load_artifact(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _geometry(points: list[dict]) -> GeometryWindow:
    return GeometryWindow.from_points(
        GeometryPoint(f"P{i}", datetime.fromisoformat(p["timestamp"]), Decimal(p["price"]),
                      PointSource.MANUAL_SEED, datetime.fromisoformat(p.get("confirmed_at", p["timestamp"])))
        for i, p in enumerate(points)
    )


def validate_seed(points: list[dict]) -> tuple[bool, str]:
    if len(points) != 5:
        return False, f"SELECT_5_POINTS ({len(points)}/5)"
    try:
        timestamps=[datetime.fromisoformat(p["timestamp"]) for p in points]
        prices=[Decimal(p["price"]) for p in points]
    except Exception as exc:
        return False, f"INVALID_VALUE: {exc}"
    if timestamps != sorted(timestamps) or len(set(timestamps)) != 5:
        return False, "TIMESTAMPS_MUST_BE_UNIQUE_AND_INCREASING"
    if len({(p["timestamp"],p["price"]) for p in points}) != 5 or any(not p.is_finite() for p in prices):
        return False, "POINTS_MUST_BE_UNIQUE_WITH_FINITE_PRICES"
    return True, "MECHANICALLY_VALID"


def directions_alternate(points: list[dict]) -> bool:
    deltas=[Decimal(b["price"])-Decimal(a["price"]) for a,b in zip(points,points[1:])]
    return all(delta != 0 for delta in deltas) and all((a > 0) != (b > 0) for a,b in zip(deltas,deltas[1:]))


def projection(points: list[dict]) -> dict:
    a=Decimal(points[-2]["price"]); b=Decimal(points[-1]["price"]); leg=b-a
    direction="DOWN" if leg>0 else "UP"
    return {"direction":direction, "cop_price":str(b-leg*Decimal("0.618")),
            "op_price":str(b-leg*Decimal("1.000")), "xop_price":str(b-leg*Decimal("1.618")),
            "a_price":str(a),"b_price":str(b),"leg":str(leg),
            "projection_algorithm":"ROLLING_OBJECTIVES", "projection_algorithm_version":2}


def candidate_progress(candles: list[dict], points: list[dict], levels: dict, end_date: str | None) -> dict | None:
    after = points[-1]["timestamp"]; direction = levels["direction"]
    active = [c for c in candles if c["open_time_utc"] > after and (not end_date or c["open_time_utc"][:10] <= end_date)]
    events = {}
    for name in ("COP", "OP", "XOP"):
        level = Decimal(levels[f"{name.lower()}_price"])
        for candle in active:
            reached = Decimal(candle["low"]) <= level if direction == "DOWN" else Decimal(candle["high"]) >= level
            if reached:
                events[name] = {"objective":name, "price":str(level), "reached_at":candle["open_time_utc"]}
                break
    deepest = next((name for name in reversed(("COP","OP","XOP")) if name in events), None)
    return {"objective":deepest, "events":events, **events[deepest]} if deepest else None


def nearest_candle(candles: list[dict], clicked_x: str) -> dict:
    if isinstance(clicked_x,(int,float)):
        clicked=datetime.fromtimestamp(clicked_x/1000,tz=timezone.utc)
    else:
        clicked=datetime.fromisoformat(str(clicked_x).replace("Z","+00:00"))
        if clicked.tzinfo is None:
            clicked=clicked.replace(tzinfo=timezone.utc)
    return min(candles,key=lambda candle:abs(datetime.fromisoformat(candle["open_time_utc"])-clicked))


def place_manual_point(session: dict, role: str, clicked_x: str, clicked_y, candles: list[dict]) -> dict:
    """Place/replace one role: snap only time, preserve the user's price."""
    if session.get("locked") or role not in ROLES:
        return session
    candle=nearest_candle(candles,clicked_x)
    point={"role":role,"timestamp":candle["open_time_utc"],"price":str(clicked_y),"source":"MANUAL"}
    session["points"]=[existing for existing in session.get("points",[]) if existing.get("role")!=role]
    session["points"].append(point); session["points"].sort(key=lambda value:ROLES.index(value["role"]))
    order=session.setdefault("placement_order",[])
    if role in order: order.remove(role)
    order.append(role)
    session["active_tool"]=None
    session["message"]="PROJECTION PREVIEW — REVIEW AND LOCK" if len(session["points"])==5 else f"{role} PLACED — SELECT NEXT ROLE"
    return session


def point_rows(points: list[dict]):
    rows=[]
    by_role={point.get("role",ROLES[index]):point for index,point in enumerate(points)}
    ordered=[by_role.get(role) for role in ROLES]
    previous=None
    for index, point in enumerate(ordered):
        if point is None:
            rows.append((ROLES[index],"NOT SET")); continue
        delta = None if previous is None else Decimal(point["price"]) - Decimal(previous["price"])
        direction = "—" if delta is None else "UP" if delta > 0 else "DOWN" if delta < 0 else "FLAT"
        rows.append((ROLES[index], f"{point['timestamp']} · {point.get('source','—')} · {point['price']} · Δ {delta if delta is not None else '—'} · {direction}"))
        previous=point
    return rows


def make_figure(data, session, date_start=None, date_end=None, dma_visible=None):
    candles=[c for c in data["candles"] if (not date_start or c["open_time_utc"][:10]>=date_start) and
             (not date_end or c["open_time_utc"][:10]<=date_end)]
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.015,row_heights=[.82,.18])
    fig.add_trace(go.Candlestick(x=[c["open_time_utc"] for c in candles],open=[float(c["open"]) for c in candles],
        high=[float(c["high"]) for c in candles],low=[float(c["low"]) for c in candles],close=[float(c["close"]) for c in candles],
        increasing_line_color="#26a69a",decreasing_line_color="#ef5350",name="ETHUSDT"),row=1,col=1)
    fig.add_trace(go.Bar(x=[c["open_time_utc"] for c in candles],y=[float(c["volume"]) for c in candles],
        marker_color="#394150",name="Volume"),row=2,col=1)
    for label,length,shift in DMA_SPECS:
        points=displaced_moving_average(candles,length,shift)
        fig.add_trace(go.Scatter(x=[p.display_at for p in points],y=[float(p.value) for p in points],mode="lines",
            line={"width":1.4},name=label,visible=True if label in (dma_visible or []) else False),row=1,col=1)
    selected=session.get("points",[])
    if selected:
        for start in range(max(1,len(selected)-2)):
            tri=selected[start:start+3]
            if len(tri)>=2:
                fig.add_trace(go.Scatter(x=[p["timestamp"] for p in tri],y=[float(p["price"]) for p in tri],mode="lines+markers+text",
                    text=ROLES[start:start+len(tri)],textposition="top center",line={"color":"#2962ff","width":2},
                    marker={"size":10,"color":"#2962ff"},showlegend=False),row=1,col=1)
    if len(selected)==5:
        levels=session.get("active_projection") or projection(selected); p4=selected[-1]; future=candles[-1]["open_time_utc"] if candles else p4["timestamp"]
        for name in ("COP","OP","XOP"):
            value=float(levels[f"{name.lower()}_price"])
            fig.add_trace(go.Scatter(x=[p4["timestamp"],future],y=[float(p4["price"]),value],mode="lines+markers",
                line={"color":COLORS[name],"dash":"dot"},name=f"Projected {name}"),row=1,col=1)
    fig.update_layout(template="plotly_dark",autosize=True,paper_bgcolor="#131722",plot_bgcolor="#131722",hovermode="x unified",
        dragmode="pan",margin={"l":8,"r":62,"t":12,"b":24},xaxis_rangeslider_visible=False,uirevision=False,
        modebar={"bgcolor":"rgba(19,23,34,.85)","color":"#787b86","activecolor":"#2962ff"})
    fig.update_xaxes(showgrid=True,gridcolor="#242833",showspikes=True,spikemode="across",spikecolor="#787b86")
    fig.update_yaxes(showgrid=True,gridcolor="#242833",side="right",row=1,col=1)
    fig.update_yaxes(showgrid=False,side="right",showticklabels=False,row=2,col=1)
    return fig


def panel(data, session, end_date):
    points=session.get("points",[]); locked=session.get("locked",False); levels=session.get("active_projection")
    visible=[c for c in data["candles"] if not end_date or c["open_time_utc"][:10]<=end_date]
    candidate=candidate_progress(data["candles"],points,levels,end_date) if locked else None
    rows=[]
    if not locked:
        rows=[("MODE","SEED_CALIBRATION"),("GEOMETRY","NOT INITIALIZED")]
        selected=dict(point_rows(points))
        rows += [(role,selected.get(role,"NOT SET")) for role in ROLES]
        rows += [("Seed status",session.get("message","SELECT_5_POINTS")),
                 ("Alternation diagnostic","PASS" if len(points)==5 and directions_alternate(points) else "WARNING: leg directions do not alternate" if len(points)==5 else "PENDING")]
        rows += [("ACTIVE TOOL",session.get("active_tool") or "NONE")]
        if len(points)==5:
            levels=projection(points)
            rows += [("PROJECTION PREVIEW","READY"),("Latest A",levels["a_price"]),("Latest B",levels["b_price"]),
                     ("LEG = B - A",levels["leg"]),("Current leg","UP" if Decimal(levels["leg"])>0 else "DOWN"),
                     ("Projected C direction",levels["direction"]),("COP = B - LEG × 0.618",levels["cop_price"]),
                     ("OP = B - LEG × 1.000",levels["op_price"]),("XOP = B - LEG × 1.618",levels["xop_price"])]
    else:
        rows=[("MODE","GENERATION_AUDIT"),("GENERATION",f"#{len(session.get('confirmed',[]))+1}"),*point_rows(points)]
    if levels:
        rows += [("CURRENT LEG","DOWN" if levels["direction"]=="UP" else "UP"),
                 ("COP",levels["cop_price"]),("OP",levels["op_price"]),("XOP",levels["xop_price"]),
                 ("Expected C direction",levels["direction"]),("Candidate objective",candidate["objective"] if candidate else "—"),
                 ("Candidate reached at",candidate["reached_at"] if candidate else "—")]
        rows += [(f"{label} state",dma_state(visible,length,shift)) for label,length,shift in DMA_SPECS]
        rows += [("COP reached","YES" if candidate and "COP" in candidate["events"] else "NO"),
                 ("OP reached","YES" if candidate and "OP" in candidate["events"] else "NO"),
                 ("XOP reached","YES" if candidate and "XOP" in candidate["events"] else "NO"),
                 ("C confirmation status","SHIFT_PREVIEW" if session.get("shift_preview") else "MANUAL_PENDING"),
                 ("Confirmed generations",len(session.get("confirmed",[])))]
        if candidate:
            rows += [("NEW PHYSICAL C objective",candidate["objective"]),("Objective price",candidate["price"]),
                     ("Objective reached at",candidate["reached_at"])]
        preview=session.get("shift_preview")
        if preview:
            rows += [("SHIFT PREVIEW","P0 P1 P2 P3 P4 → P1 P2 P3 P4 P5"),
                     ("Confirmation timestamp",preview["confirmation"]["confirmed_at"]),
                     ("Confirmation market price",preview["confirmation"]["confirmation_price"]),
                     ("NEXT COP",preview["next_projection"]["cop_price"]),("NEXT OP",preview["next_projection"]["op_price"]),
                     ("NEXT XOP",preview["next_projection"]["xop_price"])]
    return html.Div([html.Div([html.Span(k),html.Strong(str(v))],className="metric") for k,v in rows])


def create_app(artifact: Path, seed_dir: Path):
    data=load_artifact(artifact); seed_dir.mkdir(parents=True,exist_ok=True); app=Dash(__name__)
    initial={"points":[],"placement_order":[],"active_tool":None,"locked":False,"confirmed":[],
             "message":"SELECT A POINT TOOL: A0 / B0 / C0 / A1 / B1"}
    end=data["range_end"][:10]; start=(datetime.fromisoformat(end)-timedelta(days=30)).date().isoformat()
    app.layout=html.Div([html.Header([html.Div([html.Span("RG",className="brand"),html.B("Rolling Geometry V2")]),
        html.Div([html.B(data["symbol"]),html.Span(" · Spot · Binance · "),html.B("4H")],className="ticker"),html.Div("ROLLING_OBJECTIVES v2",className="algo")]),
        html.Div([html.Div([html.Div(id="mode-banner",className="mode-banner"),html.Div([html.Button("← previous period",id="prev-period"),
            html.Button("next period →",id="next-period"),dcc.DatePickerRange(id="dates",start_date=start,end_date=end),
            *[html.Button(label,id=f"range-{days}") for label,days in (("30D",30),("60D",60),("90D",90),("180D",180))],
            dcc.Checklist([{"label":name,"value":name} for name,_,_ in DMA_SPECS],value=[],id="dma-visible"),
            *[html.Button(role,id=f"tool-{role.lower()}",className="point-tool") for role in ROLES],
            html.Button("SNAP TO HIGH",id="snap-high"),html.Button("SNAP TO LOW",id="snap-low"),html.Button("LOCK SEED",id="lock-seed"),
            html.Button("UNDO LAST POINT",id="undo-point"),html.Button("CLEAR ALL",id="clear-seed"),
            html.Button("CONFIRM C",id="confirm-c"),html.Button("NOT YET",id="not-yet"),html.Button("ACCEPT SHIFT",id="accept-shift")],className="controls"),
            dcc.Graph(id="chart",className="tv-chart",style={"height":"calc(100vh - 182px)","minHeight":"460px"},
                config={"responsive":True,"scrollZoom":True,"displaylogo":False}),html.Div(id="seed-status",className="seedbar"),dcc.Store(id="session",data=initial),dcc.Store(id="manual-click")],className="chartcol"),
            html.Aside(id="panel")],className="grid")],className="app")

    @app.callback(Output("session","data"),Output("dma-visible","value"),Input("manual-click","data"),
                  *[Input(f"tool-{role.lower()}","n_clicks") for role in ROLES],Input("lock-seed","n_clicks"),Input("undo-point","n_clicks"),
                  Input("clear-seed","n_clicks"),Input("snap-high","n_clicks"),Input("snap-low","n_clicks"),Input("confirm-c","n_clicks"),Input("not-yet","n_clicks"),
                  Input("accept-shift","n_clicks"),State("session","data"),State("dates","end_date"),prevent_initial_call=True)
    def mutate(manual_click,*args):
        tool_clicks=args[:5]; lock,undo,clear,snap_high,snap_low,confirm,reject,accept,session,end_date=args[5:]
        trigger=callback_context.triggered_id
        if trigger=="clear-seed": return dict(initial),[]
        if trigger and trigger.startswith("tool-") and not session["locked"]:
            session["active_tool"]=trigger.removeprefix("tool-").upper(); session["message"]=f"ACTIVE_TOOL={session['active_tool']} — CLICK PRICE CHART"; return session,no_update
        if trigger=="undo-point" and not session["locked"]:
            order=session.get("placement_order",[])
            if order:
                role=order.pop(); session["points"]=[p for p in session["points"] if p.get("role")!=role]; session["active_tool"]=role; session["message"]=f"{role} REMOVED — CLICK TO REPLACE"
            return session,no_update
        if trigger=="manual-click" and session.get("active_tool") and manual_click:
            session=place_manual_point(session,session["active_tool"],manual_click["x"],manual_click["y"],data["candles"]); return session,no_update
        if trigger in ("snap-high","snap-low") and not session["locked"]:
            role=session.get("active_tool"); point=next((p for p in session["points"] if p.get("role")==role),None)
            if not point: session["message"]="SELECT AN EXISTING POINT TOOL TO SNAP"; return session,no_update
            candle=next(c for c in data["candles"] if c["open_time_utc"]==point["timestamp"]); source="HIGH" if trigger=="snap-high" else "LOW"
            point["price"]=candle[source.lower()]; point["source"]=f"SNAP_{source}"; session["message"]=f"{role} SNAPPED TO {source}"; return session,no_update
        if trigger=="lock-seed":
            valid,message=validate_seed(session["points"]); session["message"]=message
            if valid and directions_alternate(session["points"]):
                session["locked"]=True; session["active_projection"]=projection(session["points"])
                session["message"]="USER_LOCKED_VALID"; session["shift_preview"]=None
                seed={"seed_id":f"ETHUSDT_4H_USER_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}","status":"USER_LOCKED_VALID","points":session["points"]}
                (seed_dir/f"{seed['seed_id']}.json").write_text(json.dumps(seed,indent=2),encoding="utf-8")
                return session,["DMA 3x3"]
            if valid: session["message"]="WARNING: leg directions do not alternate — EDIT POINTS"
            return session,no_update
        if trigger=="not-yet": session["message"]="C_REJECTED_NOT_YET"; return session,no_update
        if trigger=="confirm-c" and session["locked"]:
            candidate=candidate_progress(data["candles"],session["points"],session["active_projection"],end_date)
            if not candidate: session["message"]="NO_OBJECTIVE_REACHED"; return session,no_update
            eligible=[c for c in data["candles"] if c["open_time_utc"]>=candidate["reached_at"] and (not end_date or c["open_time_utc"][:10]<=end_date)]
            if not eligible: session["message"]="NO_CONFIRMATION_CANDLE"; return session,no_update
            candle=eligible[-1]; physical={"timestamp":candidate["reached_at"],"price":candidate["price"],"confirmed_at":candle["close_time_utc"]}
            next_points=session["points"][1:]+[physical]
            confirmation={"objective_type":candidate["objective"],"objective_price":candidate["price"],
                "objective_reached_at":candidate["reached_at"],"confirmed_at":candle["close_time_utc"],"confirmation_price":candle["close"]}
            session["shift_preview"]={"new_point":physical,"next_points":next_points,"next_projection":projection(next_points),"confirmation":confirmation}
            session["message"]="SHIFT PREVIEW READY — REVIEW THEN ACCEPT SHIFT"; return session,no_update
        if trigger=="accept-shift" and session.get("shift_preview"):
            preview=session["shift_preview"]; session["confirmed"].append(preview["confirmation"]); session["points"]=preview["next_points"]
            session["points"]=[{**point,"role":ROLES[index]} for index,point in enumerate(session["points"])]
            session["active_projection"]=preview["next_projection"]; session["shift_preview"]=None; session["message"]="SHIFT_ACCEPTED"
            return session,no_update
        return session,no_update

    @app.callback(Output("chart","figure"),Output("panel","children"),Output("seed-status","children"),Output("mode-banner","children"),Output("lock-seed","disabled"),
                  Input("session","data"),Input("dates","start_date"),Input("dates","end_date"),Input("dma-visible","value"))
    def render(session,date_start,date_end,dma_visible):
        details=" | ".join(f"{role}: {p['timestamp']} @ {p['price']}" for role,p in zip(ROLES,session.get("points",[])))
        banner=(f"GEOMETRY: NOT INITIALIZED — ACTIVE_TOOL={session.get('active_tool') or 'NONE'}" if not session.get("locked") else
                f"GENERATION #{len(session.get('confirmed',[]))+1} — MANUAL AUDIT")
        return make_figure(data,session,date_start,date_end,dma_visible),panel(data,session,date_end),f"{session['message']}  {details}",banner,len(session.get("points",[])) != 5 or session.get("locked",False)

    @app.callback(*[Output(f"tool-{role.lower()}","className") for role in ROLES],Input("session","data"))
    def highlight_tool(session):
        return tuple("point-tool active" if session.get("active_tool")==role else "point-tool" for role in ROLES)

    @app.callback(Output("dates","start_date"),Output("dates","end_date"),Input("prev-period","n_clicks"),Input("next-period","n_clicks"),
                  Input("range-30","n_clicks"),Input("range-60","n_clicks"),Input("range-90","n_clicks"),Input("range-180","n_clicks"),
                  State("dates","start_date"),State("dates","end_date"),prevent_initial_call=True)
    def navigate_period(prev,next_,r30,r60,r90,r180,start_date,end_date):
        start_at=datetime.fromisoformat(start_date); end_at=datetime.fromisoformat(end_date); trigger=callback_context.triggered_id
        if trigger in ("prev-period","next-period"):
            width=end_at-start_at; shift=-width if trigger=="prev-period" else width
            return (start_at+shift).date().isoformat(),(end_at+shift).date().isoformat()
        days=int(trigger.split("-")[1]); return (end_at-timedelta(days=days)).date().isoformat(),end_at.date().isoformat()
    return app


def main():
    p=argparse.ArgumentParser(); p.add_argument("--artifact",type=Path,required=True); p.add_argument("--seed-dir",type=Path,default=Path("/var/tmp/traiding_pilot_ui_seeds")); p.add_argument("--host",default="0.0.0.0"); p.add_argument("--port",type=int,default=8055); a=p.parse_args()
    create_app(a.artifact,a.seed_dir).run(host=a.host,port=a.port,debug=False)


if __name__=="__main__": main()
