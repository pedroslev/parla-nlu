# 10. Troubleshooting and glossary

**English** · [Español](10-troubleshooting_es.md)

Find your problem below. Each one lists the most likely causes first. If nothing works, write down what you did,
what you expected and what happened (a screenshot helps) and send it to your administrator. The technical
[FAQ](../faq.md) has more answers for IT.

## The bot

### The bot doesn't understand something

1. **Try it** in the panel and read the line under your message.
   - **It wasn't sure. Closest match: …** → click **Teach it**, choose the intent, then **Train**.
   - **Understood: (another intent)** → add the phrase to the right intent, train, and open the training window
     (click **Trained …** at the top) to see **Which intents it confuses**.
2. Did you **train** after the last change? If the top bar says **Untrained changes**, click **Train**.
3. Is it a **new topic**? Create an intent and its flow, or add the answer to **Knowledge**.
4. Does it fail with **real customers** but not with you? Check **Improve**: customers write differently than you.

See [How the bot understands](02-understanding.md#when-the-bot-doesnt-understand).

### It answers things nobody asked

The bot is too eager: a message vaguely similar to an intent passes the minimum.

- In **Settings**, move **How confident it must be to reply** toward **Strict**.
- Check that no intent has very generic phrases ("I have a question", "help").
- If it's answering from Knowledge with unrelated texts, raise **How similar it has to be** in **Knowledge**.

### It keeps asking the same thing, or saves the wrong value

Open **What the bot has stored** at the bottom of the Try it panel and look at the slots.

- **The answer doesn't match the entity.** If the question's slot is linked to a list entity, only listed options
  (or their synonyms) are accepted. Add the synonym (**Teach it** under the message, or in **Entities**).
- **The slot is linked to the wrong entity.** Check it in **Slots**. A slot for a free text (an address, a comment)
  shouldn't be linked to any entity.
- **A number in the answer "corrected" another value.** With **Correct a value** on, an answer like "12 Baker St"
  can be read as a correction of a number the bot already asked for (the quantity). Ask the free-text questions
  first and the numeric ones later, or turn **Correct a value** off.
- **The question is skipped when you don't expect it.** A question is skipped when its slot already has a value. If
  you reuse a flow (a second order), clear the slots with **Set a value → clear it** at the end of the flow.

### The bot replies with nothing

- In Try it you see **The flow didn't reply anything. Check that it has a message.** → the flow has no **Send a
  message** step (or all of them are inside a branch that wasn't taken).
- A **system flow** caught the message. Very short trigger phrases ("how?") can catch real questions ("how can I
  pay?"). Check **Phrases that trigger it** in **Repeat**, **Cancel** and the others.
- The conversation is **in the Inbox** waiting for a person: the bot stays silent until someone clicks **Hand back to
  the bot**.

### My changes don't show up

- Phrases or entities changed? **Train**.
- In the Try it panel, check **Which version to try**: if it says **Production (v1)** you're testing the published
  version, not your draft.
- Customers on your website, WhatsApp, Telegram or phone get the version in **Production**. **Publish** your changes.

### The Talk with AI step doesn't work

The step shows **AI is turned off**. Turn AI on in **AI** (and make sure the model is ready) or ask your
administrator. See [Knowledge and AI](04-knowledge-and-ai.md).

## Testing and publishing

### Publishing is blocked by failing tests

You saw **Not published: 1 of 2 tests failed.** Read the failure: it says, turn by turn, what was expected and what
came back.

- If the **bot** is wrong, fix it, run the tests again and publish.
- If the **test** is out of date (you changed a message on purpose), update the test in **Tests** and publish.
- **Publish anyway** is for emergencies. Fix the test right after.

### "There's nothing new to publish"

The draft is identical to the last version. If you wanted to put an existing version in Production, do it from
**Versions** (**Put in Production** or **Move to Production**).

### I published something wrong

Go to **Versions** and click **Roll back to the previous version** on the Production card, or **Put in Production**
on a version that worked. See [Rolling back](05-testing-and-publishing.md#rolling-back).

## Voice doesn't work

- **Call (voice) is greyed out** or the microphone button doesn't appear: the browser can't use the microphone, or
  voice isn't installed on the server. Try Chrome or Edge, and ask your administrator to install voice (see
  [ai-and-voice.md](../ai-and-voice.md#voice)).
- **"I don't have permission to use the microphone"**: click the lock icon in the address bar, allow the
  microphone, and try again.
- **It works on the computer where Parla runs but not from other computers**: browsers only allow the microphone on
  secure (https) addresses. Ask IT for an HTTPS address.
- **"I didn't hear anything"**: speak closer to the microphone, or check the right microphone is selected in your
  computer's settings.
- **The voice sounds wrong or in another language**: in **AI → Bot voice**, choose a voice for the bot's language.

## Channels

### WhatsApp doesn't answer

Check in **Channels → WhatsApp**, in this order:

1. **Answer on WhatsApp** is on.
2. The **Public address of Parla** is filled in and starts with https://.
3. No secret says **Missing**.
4. The callback URL and verify token are configured in Meta and subscribed to "messages" (ask whoever manages Meta).
5. **Last message received**: if it says *none since Parla started*, messages aren't reaching Parla (address or Meta
   setup). If messages arrive but there's no **Last reply sent**, read **Last error**.
6. The customer's conversation isn't stuck **in the Inbox** waiting for a person.
7. To write first or after 24 hours of silence, WhatsApp requires an **approved template**.

### Telegram doesn't answer

Turn on **Answer on Telegram**, check the token isn't **Missing**, and click **Connect webhook** again (needed if
the public address changed). Read **Last error**.

### The website chat doesn't appear

- **Turn on the chat on my site** is on.
- Your site's address is in **Allowed sites**, exactly as the browser shows it (with or without www, add both).
  If the chat says *This site is not allowed to use this chat*, the address doesn't match.
- Parla has a public address and the snippet points to it.
- The snippet is pasted in the page (ask whoever manages the website to check).

### Phone calls don't connect

Check **Answer phone calls** is on, no secret is **Missing**, and the two URLs are pasted in the provider exactly
where the screen says. If transfers to a person fail, check the number in **Transfer to a person**.

## Access

### I can't sign in

- **Wrong user or password**: there's no "forgot my password" button. Ask an **Owner** to set a new one for you
  (**Manage users → Change password**).
- **With your company account (SSO)**: see the messages in
  [Signing in with your company account](09-administration.md#signing-in-with-your-company-account-sso).
- **The only owner lost the password**: someone technical can recover access from the server, but the other users
  and their API keys are lost (see the [FAQ](../faq.md)). That's why it's worth having two owners.

### I can't see an agent or a section

Your role or your agent list doesn't include it. **Support** works in the Inbox; **Analysts** see but don't change;
and non-owners may only see some agents. Ask an Owner (see [Users and roles](09-administration.md#users-and-roles)).

### "Couldn't save"

Your session may have expired, or you don't have permission to edit (Analyst or Support). Reload the page and sign in
again. If you're an Editor and it persists, tell your administrator.

## Glossary

| Term | Meaning |
|---|---|
| **Agent** | A bot. Each one has its own intents, flows, settings and conversations. |
| **API** | The door other programs use to talk to Parla. Used by developers. |
| **API key** | A password for a program, created for a user and with that user's permissions. |
| **Audit log** | The record of who changed what in Parla. |
| **Branch** | A flow step that does one thing or another depending on a slot. |
| **Channel** | Where the conversation happens: website, WhatsApp, Telegram, phone, test chat. |
| **Classification** | A label that records how a conversation ended ("Order placed"), for reports. |
| **Confidence** | How sure the bot is that it understood an intent, as a percentage. |
| **CSAT / Satisfaction** | The 1 to 5 rating customers give in the closing survey. |
| **Draft** | The version of the bot you're editing. |
| **Entity** | A piece of data the bot extracts from a message: a flavor, a number, a date. |
| **Environment** | Where a version is placed: **Staging** (to review) or **Production** (what customers get). |
| **Example phrase** | A way people ask for something, used to teach an intent. |
| **Fallback** | What the bot does when it doesn't understand ("Sorry, I didn't get that"). The *fallback rate* is how often it happens. |
| **Flow** | The script of what the bot says and does for an intent, step by step. |
| **Handoff** | Passing a conversation from the bot to a person in the Inbox. |
| **Inbox** | Where your team answers the conversations handed off by the bot. |
| **Intent** | Something people ask the bot for ("order a pizza"). |
| **Knowledge** | Documents the bot can answer from. |
| **Local** | Runs on your own computer or server; nothing is sent to other companies. |
| **MCP** | A standard way to connect AI assistants and tools. Used by **Connect to AI** and by the Talk with AI step's tools. |
| **Model (AI)** | The language model that powers the AI features, local (Ollama) or from a provider. |
| **Provider** | A company that runs AI or voice for you (OpenAI, Anthropic, Google…), usually paid and in the cloud. |
| **Public address** | The internet address (https) where Parla can be reached by WhatsApp, Telegram, phone providers and your website. |
| **Publish** | Save a fixed, numbered version of the bot and place it in an environment. |
| **Role** | What a user can do: Owner, Editor, Analyst or Support. |
| **Rollback** | Putting a previous version back in Production. |
| **Secret** | A password or key for another system, stored safely and never shown again. |
| **Slot** | A box where the bot writes down a piece of data during the conversation. |
| **SSO** | Signing in with your company account instead of a Parla password. |
| **Synonym** | Another way to say an option of a list entity ("marg" for margherita). |
| **System flow** | A built-in behavior that works in any flow: cancel, repeat, hand off to a person… |
| **Test** | A sample conversation with the expected results, re-run to check nothing broke. |
| **Train** | Make the bot study the current example phrases and entities. |
| **Version** | A fixed, numbered copy of the bot (v1, v2…). |
| **Webhook** | An address where another service (WhatsApp, Telegram, Twilio) sends messages to Parla. |
| **Widget** | The chat button for your website. |
