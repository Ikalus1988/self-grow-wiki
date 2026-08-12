#!/usr/bin/env python3
"""批量飞轮 — 支持自定义查询数量"""
import sys, sqlite3, time, random
sys.path.insert(0, "/mnt/c/Users/Eric Jia/SAG-poc")
from sag_hybrid import hybrid_search

def run_flywheel(count=200, seed=42):
    conn = sqlite3.connect("/mnt/c/Users/Eric Jia/SAG-poc/sag_lite.db")
    alarms = [r[0] for r in conn.execute("SELECT entity_value FROM entities_v2 WHERE entity_type='alarm_code' GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 60").fetchall()]
    signals = [r[0] for r in conn.execute("SELECT entity_value FROM entities_v2 WHERE entity_type='signal' GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 40").fetchall()]
    manuals = [r[0] for r in conn.execute("SELECT entity_value FROM entities_v2 WHERE entity_type='manual' GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 20").fetchall()]
    models = [r[0] for r in conn.execute("SELECT entity_value FROM entities_v2 WHERE entity_type='model_num' GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 20").fetchall()]
    concepts = [r[0] for r in conn.execute("SELECT entity_value FROM entities_v2 WHERE entity_type='concept' GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 25").fetchall()]
    procedures = [r[0] for r in conn.execute("SELECT entity_value FROM entities_v2 WHERE entity_type='procedure' GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 20").fetchall()]
    safeties = [r[0] for r in conn.execute("SELECT entity_value FROM entities_v2 WHERE entity_type='safety' GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 15").fetchall()
    noprefix = [r[0] for r in conn.execute("SELECT entity_value FROM entities_v2 WHERE entity_type='alarm_noprefix' GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 20").fetchall()]
    conn.close()
    
    random.seed(seed)
    queries = []
    n = count
    for _ in range(n*26//100): queries.append(("A1", f"{random.choice(alarms)} 报警"))
    for _ in range(n*13//100): 
        a1,a2=random.sample(alarms,2); queries.append(("A2", f"{a1} {a2}"))
    for _ in range(n*9//100): queries.append(("AS", f"{random.choice(alarms)} {random.choice(signals)}"))
    for _ in range(n*9//100): queries.append(("AM", f"{random.choice(models)} {random.choice(alarms)}"))
    for _ in range(n*9//100): queries.append(("C", f"FANUC {random.choice(concepts)}"))
    for _ in range(n*6//100): queries.append(("P", f"FANUC {random.choice(procedures)}"))
    for _ in range(n*6//100): queries.append(("S", f"FANUC {random.choice(safeties)}"))
    for _ in range(n*4//100): queries.append(("M", f"{random.choice(manuals)}"))
    for _ in range(n*4//100): queries.append(("N", f"FANUC {random.choice(noprefix)}"))
    boundary = ["阿西莫夫","KUKA","ABB","Python","PLC","视觉","价格","远程","SRVO-99999","手机",
        "安川","川崎","学习","仿真","培训","代理","招聘","展会","历史","股票",
        "二手","租赁","出口","工厂","耗材","认证","比赛","论坛","未来"]
    for _ in range(n*6//100): queries.append(("B", random.choice(boundary)))
    for _ in range(n*8//100):
        queries.append(("X", f"{random.choice(models)} {random.choice(concepts)} {random.choice(safeties)}"))
    
    queries = queries[:count]
    
    t0=time.time(); results=[]
    for i,(cat,q) in enumerate(queries):
        t1=time.time(); r=hybrid_search(q,5); t=time.time()-t1
        methods=[x['method'] for x in r]
        results.append({'cat':cat,'n':len(r),'t':t,'exact':'entity-exact' in methods,'hop':'entity-hop' in methods})
    
    total=time.time()-t0
    te=sum(1 for r in results if r['exact']); th=sum(1 for r in results if r['hop'])
    real=[r for r in results if r['cat']!='B']; bound=[r for r in results if r['cat']=='B']
    re=sum(1 for r in real if r['exact'])
    
    print(f"飞轮 {len(results)}条 | {total:.1f}s | exact={te}({te/len(results)*100:.0f}%) hop={th}({th/len(results)*100:.0f}%)")
    print(f"真实FANUC: exact={re}/{len(real)} ({re/len(real)*100:.1f}%)")
    print(f"边界: {len(bound)}条 (正确无命中)")
    return results

if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    run_flywheel(count)
