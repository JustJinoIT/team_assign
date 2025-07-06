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

st.header("3. 출결 등록")
selected_week = st.selectbox("출결 등록 주차 선택", list(range(1, 8)))
participants = load_participants()

st.markdown("### 불참자만 체크하세요 (체크하지 않은 참가자는 출석 처리됩니다)")

absent_pre = []
absent_day = []

cols = st.columns(3)  # 불참 종류별로 3컬럼 배치 (선택지 2개 + 이름 표시)

with cols[0]:
    st.write("이름")
with cols[1]:
    st.write("사전 불참")
with cols[2]:
    st.write("당일 불참")

absent_pre_keys = []
absent_day_keys = []

for pid, pdata in participants.items():
    cols = st.columns(3)
    cols[0].write(pdata["name"])
    pre_key = f"absent_pre_{pid}"
    day_key = f"absent_day_{pid}"
    absent_pre_checked = st.checkbox("", key=pre_key)
    absent_day_checked = st.checkbox("", key=day_key)

    # 불참 체크는 둘 중 하나만 가능하게 (둘 다 체크 안 하면 출석)
    if absent_pre_checked and absent_day_checked:
        # 하나만 남기도록 강제 (사전 불참 우선)
        st.session_state[day_key] = False

# 일괄 저장 버튼
if st.button("일괄 출결 저장"):
    for pid in participants.keys():
        status = "attending"
        if st.session_state.get(f"absent_pre_{pid}", False):
            status = "absent_pre"
        elif st.session_state.get(f"absent_day_{pid}", False):
            status = "absent_day"

        db.collection("attendance").add({
            "week": str(selected_week),
            "participant_id": pid,
            "status": status
        })
    st.success("✅ 출결 상태가 저장되었습니다.")


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

    # 기본조 최대 4명 우선, 5명도 허용
    # 3명 조 최소화(출석 인원에 맞춰 조 개수 조정)
    def split_base_groups(present):
        n = len(present)
        # 4명 기준 최소 조 수
        min_groups = max(1, n // 4)
        max_groups = min(6, n // 3)  # 최대 6개 조 제한 (요구조건)
        for g in range(min_groups, max_groups+1):
            size = n // g
            rem = n % g
            if size == 4 or (size == 3 and rem == 0):
                # 4명 조 또는 3명 조 완벽 분할
                groups = []
                idx = 0
                for i in range(g):
                    group_size = size + (1 if i < rem else 0)
                    groups.append(present[idx:idx+group_size])
                    idx += group_size
                return groups
        # 안 맞으면 기본 4명씩
        groups = [present[i:i+4] for i in range(0, n, 4)]
        # 3명 조가 생기면 5명 조로 합치기 시도
        if len(groups) > 1 and len(groups[-1]) == 3:
            groups[-2].extend(groups[-1])
            groups.pop()
        return groups

    base_groups = split_base_groups(present)

    # 활동조: 아티클 4개 기준으로 배정
    article_list = articles.get(str(selected_week), [])
    article_ids = [a['id'] for a in article_list if a['title'].strip() != ""]
    if len(article_ids) < 4:
        article_ids = ['A','B','C','D']  # 기본 4개 조

    # 기본조 내 활동조 아티클 겹침 체크
    activity_groups = {aid: [] for aid in article_ids}

    # 조별로 아티클 배정하며 조건 맞추기 (겹침 최소화)
    base_to_activity = {}

    for group in base_groups:
        assigned_articles = set()
        base_to_activity_group = {}
        for i, pid in enumerate(group):
            # 4명 조이면 겹치지 않게 순서대로 배정
            # 5명 조이면 겹칠 수 있음
            if len(group) == 4:
                aid = article_ids[i]
            else:
                # 5명 조는 랜덤 선택
                available = [a for a in article_ids if assigned_articles.count(a) < 2] if assigned_articles else article_ids
                aid = random.choice(article_ids)
            base_to_activity_group[pid] = aid
            assigned_articles.add(aid)
            activity_groups[aid].append(pid)
        base_to_activity.update(base_to_activity_group)

    return base_groups, activity_groups

# ==== 조 배정 실행 및 저장 ====
st.header("4. 조 자동 배정 (기본조 4~5명 + 활동조 배정)")

if st.button("조 배정 실행"):
    base_groups, activity_groups = assign_groups(selected_week)
    if base_groups is None:
        st.error("조 배정 실패: 출석자가 없습니다.")
    else:
        # 기존 history 삭제
        histories = db.collection("history").where("week", "==", str(selected_week)).stream()
        for doc in histories:
            doc.reference.delete()

        # history 저장
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
        for bg, members in sorted(base_group_members.items()):
            names = ", ".join(participants[pid]['name'] for pid in members if pid in participants)
            st.write(f"{bg}: {names}")

        st.subheader("활동조")
        for ag, members in sorted(activity_group_members.items()):
            names = ", ".join(participants[pid]['name']
