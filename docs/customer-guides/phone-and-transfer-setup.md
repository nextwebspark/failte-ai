# Getting calls to your agent, and passing callers to your team

This guide is for business owners setting up LightMove. It covers two things:

1. **How callers reach your agent.** Keep your existing number, get a new one, or use your mobile.
2. **How your agent passes a caller to a person** when they ask for one.

Both are set up in LightMove under **Your agent**:
- **Phone number** covers the first.
- **What your agent knows › Pass calls to your team** covers the second.

---

## Part 1 · How callers reach your agent

Open **Phone number**. You'll be asked *"How should callers reach your agent?"* There are three answers.

| You… | Choose | What happens |
|---|---|---|
| Already have a business number customers know | **Keep my existing number** | You forward your number to your agent. Customers keep ringing the same number. |
| Want a separate number just for the agent | **Get a new number** | You put the new number on your website and Google listing. |
| Run the business from your mobile | **My mobile is my business number** | You forward your mobile to the agent when you're busy or don't answer. |

### Your agent's own number

Whichever you choose, your agent needs a number of its own. Forwarded calls go to that number, and you don't need to share it with anyone. You can get one in two ways:

- **LightMove provides it.** We set up an Irish number for your agent. *This is being rolled out now. If the screen says "Coming soon", ask us and we'll set one up for you.*
- **Use your own phone provider account.** If you already have a Twilio, Telnyx or similar account, open **Advanced: use my own phone provider account**, connect it once, and pick one of your numbers.

### Option A · Keep my existing number (most common)

**1. Choose when calls should go to your agent.**

| When | What callers experience | Code on most mobiles |
|---|---|---|
| **When we don't answer** (recommended) | Your phone rings first. After about 20 seconds, your agent picks up. | `**61*<agent number>**20#` |
| **When we're busy** | Only when your line is engaged. | `**67*<agent number>#` |
| **All calls** | Your agent answers every call. | `**21*<agent number>#` |
| **Outside opening hours** | Your agent answers only when you're closed. | Ask your phone company; not every provider offers timed forwarding. |

**2. Turn on forwarding.**
- **On a mobile:** the Phone number screen shows the exact code with your agent's number already filled in. Copy it, dial it, and press call. For example: `**61*+35315550142**20#`
- **On a landline or office phone system:** ask your phone company (eir, Vodafone, Virgin Media, BT and others) to forward calls to your agent's number. Tell them which of the options above you want.
- **To undo:** dial `##002#` on a mobile to cancel all forwarding, or ask your phone company.

> These are the standard mobile forwarding codes and work on most phones and networks. If one doesn't work on yours, your network's support line can set it up for you.

**3. Check it works.**
- Press **I've set it up – check now**, then ring your business number from a different phone.
- When your agent answers, the step turns green. Where your phone company passes it on, it also says *"Forwarded from your number"*.
- LightMove never places a test call itself. It waits for your call.

### Option B · Get a new number

1. Choose **Get a new number**.
2. Get the number as described in "Your agent's own number" above.
3. Put it on your website, Google Business Profile, social pages and signage. Calls to it go straight to your agent.

### Option C · My mobile is my business number

This works like Option A, but you forward your mobile. Most sole traders choose **When we don't answer**: you take the calls you can, and your agent catches the rest.

If you also want your agent to put callers through to a person, read the warning in Part 2 about forwarding loops.

---

## Part 2 · Passing callers to your team

When a caller asks for a person, your agent can ring a phone of your choice and put them through. Set it up in **What your agent knows › What your agent can do › Pass calls to your team**.

### What happens on a call

1. The caller asks for a person: the owner, a manager, an engineer on call, reception.
2. Your agent says *"One moment, I'm putting you through"*. The caller hears hold music while your phone rings.
3. One of two things happens next:
   - **You answer:** you're talking to the caller, and your agent drops off the call. On some phone providers you first hear a short announcement: *"You have answered a transfer call."*
   - **Nobody answers within about 30 seconds:** your agent comes back, apologises, and takes the caller's name, number and reason. The call appears in **Follow-ups** as *"Transfer not answered"*, so someone can ring them back.

If you leave the number empty, your agent never transfers. It takes a message instead.

### Which number to use

You can enter a mobile, a landline or a direct line. Type it the way you'd normally write it, for example `087 123 4567`. LightMove checks it as you type and shows how it will be saved: *"✓ Irish mobile · saved as +353 87 123 4567"*. It refuses numbers that can't be dialled.

> **Don't use the number callers ring if that number forwards to your agent.** The agent would ring your number, which forwards back to the agent, and the call goes round in a circle. LightMove refuses your agent's own number for this reason. If you forward your main line (Option A or C), enter a **different** phone, such as your mobile, a colleague's mobile or a direct line that isn't forwarded.

### Only during opening hours

If you set your **Opening hours** as times on *What your agent knows*, the setting **Only during opening hours** is switched on. Outside those hours your agent doesn't ring anyone. It tells the caller the team isn't available and takes a message, which appears in **Follow-ups** as a callback.

Switch it off if you want calls put through at any hour, for example for emergency call-outs.

If your hours are written as text rather than set as times, your agent always tries to put the caller through.

### What your phone shows when it rings

By default, LightMove tries to show **the caller's number** on your phone, so you know who's calling before you answer:
- **Phone numbers from Twilio or Telnyx** (including LightMove-provided numbers) show the caller's number. If the provider refuses it, the call still comes through, showing your agent's number instead.
- **Other phone providers** show your agent's number. The screen tells you which applies to you.
- **Withheld numbers:** if the caller hid their number, your phone shows your agent's number.

You can switch this off with **Show the caller's number when we pass a call to you**.

> Tip: save your agent's number in your contacts as "LightMove agent", so you can tell transferred calls apart.

### Voicemail

If your phone's voicemail answers before the 30 seconds are up, the caller ends up in your voicemail instead of leaving a message with your agent. Either set your voicemail to answer after more than 30 seconds, or turn voicemail off on the phone you use for transfers.

### Trying it out

**Try your agent** in the browser can't put callers through, because transfers only work on real phone calls. In a browser test, the agent offers to take a message instead. To test a transfer, ring your agent's number from a phone.

---

## Quick checklist

- [ ] Your agent has its own number (LightMove-provided, or from your own provider account).
- [ ] You chose how callers reach the agent, set up forwarding, and saw the check turn green.
- [ ] "Pass calls to your team" has a number that is **not** forwarded to your agent.
- [ ] Opening hours are set as times, and "Only during opening hours" is on or off as you want.
- [ ] Voicemail on that phone answers after more than 30 seconds, or is off.
- [ ] You rang your business number from another phone and asked for a person.

## Questions

- **Does a transfer cost extra?** Ringing your phone is a normal outgoing call. On your own provider account, it appears on that provider's bill. LightMove counts the time your agent is on the call, including the hold music while your phone rings, but not the conversation after you answer.
- **Can my agent ring more than one person?** Today it rings one number. Ask us if you need calls routed to different people.
- **Can I change the number later?** Yes. Edit it on *What your agent knows* and save. It applies from the next call.
