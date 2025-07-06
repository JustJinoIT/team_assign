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

# ==== 아티클 관리 ====
st.header("2. 주차별 아티클 등록")
week = st.selectbox("주차 선택", list(range(1, 8)))
article_list = db.collection("articles").where("week", "==", str(week)).stream()
article_list = [doc.to_dict() for doc in article_list]

if not article_list:
    st.warning("해당 주차에 등록된 아티클이 없습니다.")
else:
    with st.form("article_form"):
        cols = st.columns(4)
        article_data = []
        # 아티클 번호 1,2,3,4 로 변경
        article_ids = ['1', '2', '3', '4']
        for i in range(4):
            with cols[i]:
                existing = next((a for a in article_list if a['id'] == article_ids[i]), {})
                title = st.text_input(f"{article_ids[i]}번 제목", value=existing.get("title", ""), key=f"art_title_{i}")
                link = st.text_input(f"{article_ids[i]}번 링크", value=existing.get("link", ""), key=f"art_link_{i}")
                article_data.append({"week": str(week), "id": article_ids[i], "title": title, "link": link})
        if st.form_submit_button("아티클 저장"):
            arts = db.collection("articles").where("week", "==", str(week)).stream()
            for doc in arts:
                doc.reference.delete()
            for art in article_data:
                if art["title"].strip():
                    db.collection("articles").add(art)
            st.success("✅ 아티클 저장 완료")

# ==== 출결 등록 ====
st.header("3. 출결 등록")
selected_week = st.selectbox("출결 등록 주차 선택", list(range(1, 8)))
participants = load_participants()
if f"attendance_{selected_week}" not in st.session_state:
    st.session_state[f"attendance_{selected_week}"] = {}

st.markdown("#### ⛔️ 불참자만 체크하세요 (출석자는 체크할 필요 없습니다)")
cols = st.columns(5)
for idx, (pid, pdata) in enumerate(participants.items()):
    col = cols[idx % 5]
    is_absent = col.checkbox(pdata["name"], key=f"absent_{selected_week}_{pid}")
    st.session_state[f"attendance_{selected_week}"][pid] = "absent_pre" if is_absent else "attending"

if st.button("✅ 출결 저장"):
    for pid, status in st.session_state[f"attendance_{selected_week}"].items():
        db.collection("attendance").add({
            "week": str(selected_week),
            "participant_id": pid,
            "status": status
        })
    st.success("출결 상태가 저장되었습니다.")

# ==== 조 배정 알고리즘 함수 ====
def assign_groups(selected_week):
    attendance = load_attendance()
    participants = load_participants()
    articles = load_articles()

    present = [pid for pid, status in attendance.get(str(selected_week), {}).items() if status == "attending"]
    if not present:
        st.warning("출석한 참가자가 없습니다.")
        return None, None

    random.shuffle(present)

    def split_base_groups(present):
        n = len(present)
        min_groups = max(1, n // 4)
        max_groups = min(6, n // 3)
        for g in range(min_groups, max_groups+1):
            size = n // g
            rem = n % g
            if size == 4 or (size == 3 and rem == 0):
                groups = []
                idx = 0
                for i in range(g):
                    group_size = size + (1 if i < rem else 0)
                    groups.append(present[idx:idx+group_size])
                    idx += group_size
                return groups
        groups = [present[i:i+4] for i in range(0, n, 4)]
        if len(groups) > 1 and len(groups[-1]) == 3:
            groups[-2].extend(groups[-1])
            groups.pop()
        return groups

    base_groups = split_base_groups(present)

    article_list = articles.get(str(selected_week), [])
    article_ids = [a['id'] for a in article_list if a['title'].strip() != ""]
    if len(article_ids) < 4:
        article_ids = ['1', '2', '3', '4']  # 기본 4개 조

    activity_groups = {aid: [] for aid in article_ids}
    base_to_activity = {}

    for group in base_groups:
        assigned_articles = set()
        base_to_activity_group = {}
        for i, pid in enumerate(group):
            if len(group) == 4:
                aid = article_ids[i]
            else:
                aid = random.choice(article_ids)
            base_to_activity_group[pid] = aid
            assigned_articles.add(aid)
            activity_groups[aid].append(pid)
        base_to_activity.update(base_to_activity_group)

    return base_groups, activity_groups

st.header("4. 조 자동 배정 (기본조 4~5명 + 활동조 배정)")

if st.button("🚀 조 배정 재실행"):
    base_groups, activity_groups = assign_groups(selected_week)
    if base_groups is None:
        st.error("출석자가 없어 조를 배정할 수 없습니다.")
    else:
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
        st.success(f"{selected_week}주차 조 배정이 완료되었습니다.")

# ==== 조 배정 이력 확인 ====
st.header("5. 조 배정 이력 확인")
histories = load_history()
participants = load_participants()
weeks = sorted(set(h['week'] for h in histories.values()), reverse=True)
if weeks:
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
        if base_group_members:
            for bg, members in sorted(base_group_members.items()):
                names = ", ".join(participants[pid]['name'] for pid in members if pid in participants)
                st.write(f"{bg}: {names}")
        else:
            st.write("기본조 이력이 없습니다.")

        st.subheader("활동조")
        if activity_group_members:
            for ag, members in sorted(activity_group_members.items()):
                names = ", ".join(participants[pid]['name'] for pid in members if pid in participants)
                st.write(f"{ag}: {names}")
        else:
            st.write("활동조 이력이 없습니다.")

        # 조별 개인별 아티클 번호 함께 표시 (1,2,3,4)
        st.header(f"{view_week}주차 기본조 및 아티클 배정 현황")
        participant_article_map = {}
        for h in histories.values():
            if h.get("week") == view_week and "activity_group" in h:
                pid = h["participant_id"]
                article_id = h["activity_group"]
                participant_article_map[pid] = article_id

        if not base_group_members:
            st.write("조 배정 이력이 없어 아티클 배정 현황을 표시할 수 없습니다.")
        else:
            for bg, members in sorted(base_group_members.items()):
                display_names = []
                for pid in members:
                    name = participants[pid]["name"] if pid in participants else pid
                    article_num = participant_article_map.get(pid, "없음")
                    display_names.append(f"{name}({article_num})")
                st.write(f"{bg}: " + ", ".join(display_names))


