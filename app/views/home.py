"""Home: welcome, the scenario cards, and signing in as any customer. Choosing a customer is how you sign in here."""
import streamlit as st

from app import components, data, state
from app.config import load_personas

settings = state.get_settings()
personas = load_personas()
by_id = {p.customer_id: p for p in personas}


def live_line(persona) -> str | None:
    """One line read live from the tools for a card: the story item if the persona names one, else the newest order."""
    try:
        return data.story_line(settings.demo_db, persona.customer_id, persona.item_id)
    except Exception:
        return None


def start(customer_id: str, scenario: str | None) -> None:
    try:
        state.sign_in(customer_id, scenario)
    except Exception:
        st.error(settings.error_reply)
        return
    st.switch_page("views/chat.py")


st.markdown("# Hello, and welcome.")
st.markdown("### Let's sort out your return.")
st.write("This assistant handles returns, replacements, refunds and cancellations for Amazon.in orders, using the public policy pages "
         "and made-up orders, and it shows its work as it goes. Nothing changes until you say yes, and anything unusual goes to a person.")
st.html('<div class="callout"><b>Choosing a customer is how you sign in here.</b>'
        "A real store would ask for your login. This demo lets you pick a made-up customer instead, so you can try different situations. "
        "Everything the agent does is then done for that customer only.</div>")

st.markdown("## Sign in as a demo customer")
st.write("Pick a scenario. Each one signs you in as a customer with a story to try.")
cards = [p for p in personas if p.card]
for row in range(0, len(cards), 3):
    for col, persona in zip(st.columns(3), cards[row:row + 3]):
        with col:
            key = "start" if persona.start_here else persona.customer_id
            with st.container(key=f"scenario-card-{key}"):
                st.html(components.scenario_card_html(persona, live_line(persona)))
                if st.button("Sign in and start", key=f"start-{persona.customer_id}", type="primary", width="stretch"):
                    start(persona.customer_id, persona.title)

st.markdown("## Or sign in as any customer")
st.write("Choose from the list, or type to search by customer id. Useful for trying your own situation.")
try:
    everyone = data.list_customers(settings.demo_db)
except Exception:
    everyone = []
    st.error(settings.error_reply)


def option_text(customer_id: str) -> str:
    persona = by_id.get(customer_id)
    return f"{customer_id} · {persona.label}" if persona else customer_id


picked = st.selectbox("Customer", everyone, index=None, placeholder="Choose a customer", format_func=option_text, key="any-customer")
if picked and picked in by_id:
    st.caption(by_id[picked].hint)
if st.button("Sign in", key="sign-in-any", disabled=picked is None):
    start(picked, by_id[picked].title if picked in by_id and by_id[picked].card else None)

st.markdown("## What you can check as you go")
st.html('<div class="info-box"><ul>'
        "<li>Each answer names the policy page it came from.</li>"
        "<li>Eligibility and money are worked out by code, not by the model.</li>"
        "<li>You answer yes or no before anything is changed.</li>"
        "<li>Exceptions go to a person. The agent never grants them.</li></ul></div>")
left, right = st.columns(2)
left.page_link("views/how_it_works.py", label="How it works")
right.page_link("views/limits.py", label="Limits and assumptions")
st.caption("Read these if you want to know what is ours and not Amazon's.")
