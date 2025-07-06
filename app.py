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

# ==== 참가자 등록 ====
st.title("🧑‍🤝‍🧑 기본조 + 활동조 배정 프로그램 (Firebase 연동)")

st.header("1. 참가자 등록")
with st.form("participant_form"):
    pid = st.text_input("고유 ID (예: jinho)")
    name = st.text_input("이름")
    submit = st.form_submit_button("등록")
    if submit and pid and name:
        db.collection("participants").document(pid).set({"name": name})
        st.success(f"✅ {name} 참가자 등록 완료")

# ==== 엑셀 업로드 (중복 참가자 등록 방지 + 출결, 기본조 반영) ====
st.subheader("📥 엑셀 업로드 (참가자 중복 등록 방지 및 출결/기본조 반영)")
uploaded_file = st.file_uploader("엑셀(.xlsx) 업로드", type=["xlsx"])
if uploaded_file:
    df = pd.read_excel(uploaded_file)
    participants = load_participants()
    # 참가자 중복 확인 후 신규 등록
    for _, row in df.iterrows():
        name = str(row.get("성명", "")).strip()
        if name:
            pid = name.lower().replace(" ", "")
            if pid not in participants:
                db.collection("participants").document(pid).set({"name": name})
    # 출결 및 기본조 반영
    for week in range(1, 8):
        col = f"{week}주차"
        if col in df.columns:
            for _, row in df.iterrows():
                name = str(row.get("성명", "")).strip()
                pid = name.lower().replace(" ", "")
                val = str(row.get(col, "")).strip()
                if val == "불참":
                    status = "absent_pre"
                elif val == "-":
                    status = "absent_day"
                elif val.endswith("조"):
                    status = "attending"
                else:
                    status = "absent_pre"
                db.collection("attendance").add({
                    "week": str(week),
                    "participant_id": pid,
                    "status": status
                })
                # 기본조 저장
                if val.endswith("조"):
                    db.collection("history").add({
                        "week": str(week),
                        "base_group": val,
                        "participant_id": pid
                    })
    st.success("✅ 엑셀에서 참가자 및 출결, 기본조 반영 완료")

# ==== 아티클 관리 ====
st.header("2. 주차별 아티클 등록")
week = st.selectbox("주차 선택", list(range(1, 8)))
with st.form("article_form"):
    cols = st.columns(4)
    article_data = []
    for i in range(4):
        with cols[i]:
            title = st.text_input(f"{i+1}번 제목", key=f"art_title_{i}")
            link = st.text_input(f"{i+1}번 링크", key=f"art_link_{i}")
            article_data.append({"week": str(week), "id": chr(65+i), "title": title, "link": link})
    if st.form_submit_button("아티클 저장"):
        arts = db.collection("articles").where("week", "==", str(week)).stream()
        for doc in arts:
            doc.reference.delete()
        for art in article_data:
            db.collection("articles").add(art)
        st.success("✅ 아티클 저장 완료")

# ==== 출결 등록 (기본값 출석) ====
st.header("3. 출결 등록")
selected_week = st.selectbox("출결 등록 주차 선택", list(range(1, 8)))
participants = load_participants()
for pid, pdata in participants.items():
    status = st.radio(f"{pdata['name']} 출결 상태", ["attending", "absent_pre", "absent_day"], index=0, key=f"att_{pid}")
    if st.button(f"{pdata['name']} 출결 저장", key=f"save_att_{pid}"):
        db.collection("attendance").add({
            "week": str(selected_week),
            "participant_id": pid,
            "status": status
        })
        st.success(f"{pdata['name']} 출결 저장 완료")

# ==== 조 자동 배정 ====
st.header("4. 조 자동 배정 (기본조 4~5명 + 활동조 배정)")
if st.button("조 배정 실행"):
    attendance = load_attendance()
    participants = load_participants()
    articles = load_articles()
    present = [pid for pid, status in attendance.get(str(selected_week), {}).items() if status == "attending"]
    random.shuffle(present)

    base_groups = [present[i:i+4] for i in range(0, len(present), 4)]
    if base_groups:
        if len(base_groups[-1]) == 3 and len(present) % 4 != 0:
            if len(base_groups) > 1:
                base_groups[-2].append(base_groups[-1].pop())

    article_ids = [a['id'] for a in articles.get(str(selected_week), [])]
    activity_groups = {aid: [] for aid in article_ids}
    for pid in present:
        aid = random.choice(article_ids) if article_ids else None
        if aid:
            activity_groups[aid].append(pid)

    histories = db.collection("history").where("week", "==", str(selected_week)).stream()
    for doc in histories:
        doc.reference.delete()

    for idx, group in enumerate(base_groups, start=1):
        for pid in group:
            db.collection("history").add({
                "week": str(selected_week),
                "base_group": f"{idx}조",
                "participant_id": pid
            })

    for aid, members in activity_groups.items():
        for pid in members:
            db.collection("history").add({
                "week": str(selected_week),
                "activity_group": aid,
                "participant_id": pid
            })
    st.success(f"✅ {selected_week}주차 조 배정 완료")

# ==== 조 배정 이력 확인 ====
st.header("5. 조 배정 이력 확인")
histories = load_history()
participants = load_participants()
weeks = sorted(set(h['week'] for h in histories.values()), reverse=True)
view_week = st.selectbox("이력 확인 주차 선택", weeks)
if view_week:
    base_group_members = defaultdict(list)
    activity_group_members = defaultdict(list)
    for h in histories.values():
        if h['week'] == view_week:
            if 'base_group' in h:
                base_group_members[h['base_group']].append(h['participant_id'])
            if 'activity_group' in h:
                activity_group_members[h['activity_group']].append(h['participant_id'])

    st.subheader("기본조")
    for bg, members in base_group_members.items():
        names = ", ".join(participants[pid]['name'] for pid in members if pid in participants)
        st.write(f"{bg}: {names}")

    st.subheader("활동조")
    for ag, members in activity_group_members.items():
        names = ", ".join(participants[pid]['name'] for pid in members if pid in participants)
        st.write(f"{ag}: {names}")
