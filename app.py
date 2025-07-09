import streamlit as st 
import json
import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict
import random
import pandas as pd

# ==== Firebase 초기화 ====
if not firebase_admin._apps:
    service_account_info = json.loads(st.secrets["firebase"]["service_account_json"])
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==== 유틸 함수 ====
def load_participants():
    docs = db.collection("participants").stream()
    return {doc.id: doc.to_dict() for doc in docs}

def load_articles():
    docs = db.collection("articles").stream()
    result = defaultdict(list)
    for doc in docs:
        data = doc.to_dict()
        week = data.get("week")
        if week:
            result[str(week)].append(data)
    return dict(result)

def load_history():
    docs = db.collection("history").stream()
    return {doc.id: doc.to_dict() for doc in docs}

def load_attendance():
    docs = db.collection("attendance").stream()
    result = defaultdict(dict)
    for doc in docs:
        data = doc.to_dict()
        week = data.get("week")
        pid = data.get("participant_id")
        status = data.get("status")
        if week and pid:
            result[str(week)][pid] = status
    return dict(result)

def assign_groups(week, present, article_list):
    article_ids = [a['id'] for a in article_list] if article_list else ['1', '2', '3', '4']
    random.shuffle(present)

    def split_base_groups():
        n = len(present)
        q, r = divmod(n, 4)
        group_sizes = [4] * q
        for i in range(r):
            group_sizes[i % len(group_sizes)] += 1
        groups = []
        index = 0
        for size in group_sizes:
            groups.append(present[index:index+size])
            index += size
        return groups

    base_groups = split_base_groups()

    activity_groups = defaultdict(list)
    base_to_activity = {}

    for group in base_groups:
        assigned = set()
        for i, pid in enumerate(group):
            aid = article_ids[i % len(article_ids)]
            base_to_activity[pid] = aid
            activity_groups[aid].append(pid)

    return base_groups, base_to_activity, activity_groups

def save_history(week, base_groups, activity_map):
    existing = db.collection("history").where("week", "==", str(week)).stream()
    for doc in existing:
        doc.reference.delete()

    for idx, group in enumerate(base_groups, start=1):
        for pid in group:
            db.collection("history").add({
                "week": str(week),
                "base_group": f"{idx}조",
                "participant_id": pid
            })
    for pid, aid in activity_map.items():
        db.collection("history").add({
            "week": str(week),
            "activity_group": aid,
            "participant_id": pid
        })

def render_history(week, participants):
    history = load_history()
    base_group_members = defaultdict(list)
    activity_group_members = defaultdict(list)
    article_map = {}
    for h in history.values():
        if h['week'] == str(week):
            if 'base_group' in h:
                base_group_members[h['base_group']].append(h['participant_id'])
            if 'activity_group' in h:
                activity_group_members[h['activity_group']].append(h['participant_id'])
                article_map[h['participant_id']] = h['activity_group']

    st.subheader("기본조")
    for bg, members in sorted(base_group_members.items()):
        names = ", ".join(f"{participants[pid]['name']} ({article_map.get(pid, '-')})" for pid in members if pid in participants)
        st.write(f"{bg}: {names}")

    st.subheader("활동조")
    for ag, members in sorted(activity_group_members.items()):
        names = ", ".join(participants[pid]['name'] for pid in members if pid in participants)
        st.write(f"{ag}번: {names}")

# ==== 앱 시작 ====
st.title("🧑‍🤝‍🧑 기본조 + 활동조 배정 프로그램 (최종버전)")

participants = load_participants()
articles = load_articles()
attendance = load_attendance()

# 참가자 등록
st.header("1. 참가자 등록 및 관리")
with st.form("register"):
    pid = st.text_input("ID").strip()
    name = st.text_input("이름").strip()
    if st.form_submit_button("등록") and pid and name:
        db.collection("participants").document(pid).set({"name": name})
        st.success("등록 완료")

cols = st.columns(5)
for idx, (pid, pdata) in enumerate(participants.items()):
    col = cols[idx % 5]
    if col.button(f"❌ {pdata['name']}", key=pid):
        if st.confirm(f"정말로 {pdata['name']} 참가자를 삭제하시겠습니까?"):
            db.collection("participants").document(pid).delete()
            st.experimental_rerun()

# 주차 선택
st.header("2. 주차 선택")
selected_week = st.selectbox("주차 선택", list(range(1, 8)))

# 아티클 등록
st.header("3. 아티클 등록")
with st.form("articles"):
    cols = st.columns(4)
    entries = []
    for i in range(4):
        with cols[i]:
            title = st.text_input(f"{i+1}번 제목", key=f"title_{i}")
            link = st.text_input(f"{i+1}번 링크", key=f"link_{i}")
            entries.append({"week": str(selected_week), "id": str(i+1), "title": title, "link": link})
    if st.form_submit_button("저장"):
        for doc in db.collection("articles").where("week", "==", str(selected_week)).stream():
            doc.reference.delete()
        for e in entries:
            db.collection("articles").add(e)
        st.success("저장됨")

# 출결 등록
st.header("4. 출결 등록")
if f"attendance_{selected_week}" not in st.session_state:
    st.session_state[f"attendance_{selected_week}"] = {}

cols = st.columns(5)
for idx, (pid, pdata) in enumerate(participants.items()):
    col = cols[idx % 5]
    previous = attendance.get(str(selected_week), {}).get(pid, "")
    label = pdata['name']
    if previous == "absent_pre":
        label += " (불참)"
    is_absent = col.checkbox(label, key=f"att_{pid}_{selected_week}", value=(previous == "absent_pre"))
    st.session_state[f"attendance_{selected_week}"][pid] = "absent_pre" if is_absent else "attending"

if st.button("✅ 출결 저장"):
    for pid, status in st.session_state[f"attendance_{selected_week}"].items():
        db.collection("attendance").add({"week": str(selected_week), "participant_id": pid, "status": status})
    st.success("저장 완료")

# 조 배정
st.header("5. 조 배정")
week_history = [h for h in load_history().values() if h['week'] == str(selected_week)]
article_list = articles.get(str(selected_week), [])
present = [pid for pid, status in attendance.get(str(selected_week), {}).items() if status == "attending"]

if week_history:
    if st.button("♻️ 조 배정 재실행"):
        base, amap, agroups = assign_groups(selected_week, present, article_list)
        save_history(selected_week, base, amap)
        st.success("재배정 완료")
else:
    if st.button("🚀 조 배정 실행"):
        base, amap, agroups = assign_groups(selected_week, present, article_list)
        save_history(selected_week, base, amap)
        st.success("조 배정 완료")

if st.button("⚠️ 당일 재구성"):
    base, amap, agroups = assign_groups(selected_week, present, article_list)
    save_history(selected_week, base, amap)
    st.success("당일 재구성 완료")

# 이력 보기
st.header("6. 이력 보기")
render_history(selected_week, participants)


