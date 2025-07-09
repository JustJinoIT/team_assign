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

# ==== 함수: 참가자 불러오기 ====
def load_participants():
    docs = db.collection("participants").stream()
    return {doc.id: doc.to_dict() for doc in docs}

# ==== 함수: 아티클 불러오기 ====
def load_articles():
    docs = db.collection("articles").stream()
    result = defaultdict(list)
    for doc in docs:
        data = doc.to_dict()
        week = data.get("week")
        if week:
            result[str(week)].append(data)
    return dict(result)

# ==== 함수: 히스토리 불러오기 ====
def load_history():
    docs = db.collection("history").stream()
    return {doc.id: doc.to_dict() for doc in docs}

# ==== 함수: 출결 불러오기 ====
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

st.title("🧑‍🤝‍🧑 기본조 + 활동조 배정 프로그램 (Firebase 연동)")

# ==== 1. 참가자 등록 및 관리 ====
st.header("1. 참가자 등록 및 관리")
with st.form("participant_form"):
    pid = st.text_input("고유 ID (예: jinho)")
    name = st.text_input("이름")
    submit = st.form_submit_button("등록")
    if submit and pid and name:
        db.collection("participants").document(pid).set({"name": name})
        st.success(f"✅ {name} 참가자 등록 완료")

st.subheader("참가자 목록 및 삭제")
participants = load_participants()
if participants:
    for pid, pdata in participants.items():
        col1, col2 = st.columns([4, 1])
        col1.write(pdata["name"])
        if col2.button("삭제", key=f"del_{pid}"):
            db.collection("participants").document(pid).delete()
            st.success(f"❌ {pdata['name']} 삭제 완료")
            st.experimental_rerun()

# ==== 2. 주차별 통합 관리 (아티클 + 출결 + 조 배정) ====
st.header("2. 주차별 아티클, 출결 및 조 배정")
selected_week = st.selectbox("주차 선택", list(range(1, 8)))
participants = load_participants()
attendance = load_attendance()
history = load_history()
articles = load_articles()

# ==== 아티클 등록 ====
st.subheader("📚 아티클 등록")
with st.form("article_form"):
    cols = st.columns(4)
    article_data = []
    for i in range(4):
        with cols[i]:
            title = st.text_input(f"{i+1}번 제목", key=f"art_title_{i}")
            link = st.text_input(f"{i+1}번 링크", key=f"art_link_{i}")
            article_data.append({"week": str(selected_week), "id": str(i+1), "title": title, "link": link})
    if st.form_submit_button("아티클 저장"):
        arts = db.collection("articles").where("week", "==", str(selected_week)).stream()
        for doc in arts:
            doc.reference.delete()
        for art in article_data:
            db.collection("articles").add(art)
        st.success("✅ 아티클 저장 완료")

if article_data := articles.get(str(selected_week)):
    for art in article_data:
        st.markdown(f"- {art['id']}번: [{art['title']}]({art['link']})")
else:
    st.info("해당 주차에 등록된 아티클이 없습니다.")

# ==== 출결 등록 ====
st.subheader("📌 출결 등록")
if f"attendance_{selected_week}" not in st.session_state:
    st.session_state[f"attendance_{selected_week}"] = {}

cols = st.columns(5)
for idx, (pid, pdata) in enumerate(participants.items()):
    col = cols[idx % 5]
    prev = attendance.get(str(selected_week), {}).get(pid, "attending")
    label = pdata["name"] + (" (불참)" if prev == "absent_pre" else "")
    is_absent = col.checkbox(label, key=f"absent_{selected_week}_{pid}", value=prev == "absent_pre")
    st.session_state[f"attendance_{selected_week}"][pid] = "absent_pre" if is_absent else "attending"

if st.button("✅ 출결 저장"):
    for pid, status in st.session_state[f"attendance_{selected_week}"].items():
        db.collection("attendance").add({
            "week": str(selected_week),
            "participant_id": pid,
            "status": status
        })
    st.success("출결 상태 저장 완료")

# ==== 조 배정 ====
st.subheader("🧮 조 배정")

def assign_groups(selected_week):
    present = [pid for pid, status in attendance.get(str(selected_week), {}).items() if status == "attending"]
    if not present:
        st.warning("출석한 참가자가 없습니다.")
        return [], {}
    random.shuffle(present)

    def split_base_groups(present):
        n = len(present)
        groups = [present[i:i+4] for i in range(0, n, 4)]
        if len(groups) > 1 and len(groups[-1]) == 3:
            groups[-2].extend(groups[-1])
            groups.pop()
        return groups

    base_groups = split_base_groups(present)
    article_list = articles.get(str(selected_week), [])
    article_ids = [a['id'] for a in article_list] or ['1', '2', '3', '4']

    activity_groups = {aid: [] for aid in article_ids}
    base_to_activity = {}

    for group in base_groups:
        assigned = set()
        group_activity = {}
        for i, pid in enumerate(group):
            aid = article_ids[i % len(article_ids)] if len(group) <= 4 else random.choice(article_ids)
            group_activity[pid] = aid
            assigned.add(aid)
            activity_groups[aid].append(pid)
        base_to_activity.update(group_activity)

    return base_groups, base_to_activity

existing_history = [h for h in history.values() if h['week'] == str(selected_week)]
if existing_history:
    if st.button("🔁 조 배정 재실행"):
        for doc in db.collection("history").where("week", "==", str(selected_week)).stream():
            doc.reference.delete()
        base_groups, activity_map = assign_groups(selected_week)
        for idx, group in enumerate(base_groups, start=1):
            for pid in group:
                db.collection("history").add({
                    "week": str(selected_week),
                    "base_group": f"{idx}조",
                    "participant_id": pid,
                    "activity_group": activity_map.get(pid)
                })
        st.success("조 배정 완료 및 이력 갱신")
else:
    if st.button("🚀 조 배정 실행"):
        base_groups, activity_map = assign_groups(selected_week)
        for idx, group in enumerate(base_groups, start=1):
            for pid in group:
                db.collection("history").add({
                    "week": str(selected_week),
                    "base_group": f"{idx}조",
                    "participant_id": pid,
                    "activity_group": activity_map.get(pid)
                })
        st.success("조 배정 완료")

# ==== 조 배정 이력 확인 ====
st.header("3. 조 배정 이력 및 현황")
view_week = selected_week
history = load_history()
participants = load_participants()
base_group_members = defaultdict(list)
activity_group_members = defaultdict(list)
article_assignment = defaultdict(str)

for h in history.values():
    if h['week'] == str(view_week):
        pid = h['participant_id']
        if 'base_group' in h:
            base_group_members[h['base_group']].append(pid)
        if 'activity_group' in h:
            activity_group_members[h['activity_group']].append(pid)
            article_assignment[pid] = h['activity_group']

if base_group_members:
    st.subheader("기본조 + 활동조")
    for bg, members in sorted(base_group_members.items()):
        names = [
            f"{participants[pid]['name']} ({article_assignment.get(pid, '없음')}번)"
            for pid in members if pid in participants
        ]
        st.write(f"{bg}: {', '.join(names)}")
else:
    st.info("⚠️ 조 배정 이력이 없습니다.")
