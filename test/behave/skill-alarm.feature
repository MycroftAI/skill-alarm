Feature: Alarm skill functionality

  Scenario Outline: user asks for alarm status of a single alarm
    Given an english speaking user
    And there are no previous alarms set
    And an alarm is set for 9:00 am on weekdays
    When the user says "<alarm status>"
    Then "mycroft-alarm" should reply with dialog from "alarms.list.single.dialog"

  Examples: status of a single alarm
    | alarm status |
    | alarm status |
    | do I have any alarms |
    | what alarms do I have |
    | show me my alarms |
    | when will my alarm go off |
    | when's my alarm |

  @xfail
  # Jira 69 https://mycroft.atlassian.net/browse/MS-69
  Scenario Outline: Failing user asks for alarm status of a single alarm
    Given an english speaking user
    And there are no previous alarms set
    And an alarm is set for 9:00 am on weekdays
    When the user says "<alarm status>"
    Then "mycroft-alarm" should reply with dialog from "alarms.list.single.dialog"

  Examples: status of a single alarm
    | alarm status |
    | alarm status |
    | tell me my alarms |
    | are there any alarms set |
    | what time is my alarm set to |
    | is there an alarm set |

  Scenario Outline: user asks for alarm status of multiple alarms
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on weekdays
     And an alarm is set for 6:00 pm on wednesday
     When the user says "<alarm status>"
     Then "mycroft-alarm" should reply with dialog from "alarms.list.multi.dialog"

  Examples: status of multiple alarms
    | alarm status |
    | alarm status |
    | do I have any alarms |
    | what alarms do I have |
    | show me my alarms |
    | when will my alarm go off |
    | when's my alarm |

  @xfail
  # Jira 70 https://mycroft.atlassian.net/browse/MS-70
  Scenario Outline: Failing user asks for alarm status of multiple alarms
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on weekdays
     And an alarm is set for 6:00 pm on wednesday
     When the user says "<alarm status>"
     Then "mycroft-alarm" should reply with dialog from "alarms.list.multi.dialog"

  Examples: status of multiple alarms
    | alarm status |
    | alarm status |
    | tell me my alarms |
    | are there any alarms set |
    | what time is my alarm set to |
    | is there an alarm set |

  Scenario Outline: user asks for alarm status when no alarms are sets
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<alarm status>"
     Then "mycroft-alarm" should reply with dialog from "alarms.list.empty.dialog"

  Examples: status when no alarms are set
     | alarm status |
     | alarm status |
     | do I have any alarms |
     | what alarms do I have |
     | show me my alarms |
     | when will my alarm go off |
     | when's my alarm |
     | are there any alarms set for this evening |

  @xfail
  # Jira MS-71 https://mycroft.atlassian.net/browse/MS-71
  Scenario Outline: Failing user asks for alarm status when no alarms are sets
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<alarm status>"
     Then "mycroft-alarm" should reply with dialog from "alarms.list.empty.dialog"

  Examples: status when no alarms are set
     | alarm status |
     | alarm status |
     | are there any alarms set |
     | is there an alarm set |
     | what time is my alarm set to |
     | tell me my alarms |

  Scenario Outline: user stops an expired alarm when beeping
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is expired and beeping
     When the user says "<stop>"
     Then "mycroft-alarm" should stop beeping

  Examples: stop beeping
    | stop |
    | stop |
    | stop alarm |
    | disable alarm |
    | cancel |
    | cancel alarm |
    | turn it off |
    | turn off |
    | turn off alarm |
    | silence |
    | abort |
    | kill alarm |

  @xfail
  # Jira MS-72 https://mycroft.atlassian.net/browse/MS-72
  Scenario Outline: user snoozes a beeping alarm
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is expired and beeping
     When the user says "<snooze>"
     Then "mycroft-alarm" should stop beeping and start beeping again 10 minutes

  Examples: snooze a beeping alarm
    | snooze |
    | snooze |
    | snooze alarm |
    | not yet |
    | 10 more minutes |
    | 10 minutes |
    | snooze for 10 minutes |
    | give me 10 minutes |
    | wake me up in 10 minutes |
    | remind me in 10 minutes |
    | let me sleep |

  @xfail
  # Jira MS-73 https://mycroft.atlassian.net/browse/MS-73
  Scenario Outline: user snoozes an beeping alarm for a specific time
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is expired and beeping
     When the user says "<snooze for a time>"
     Then "mycroft-alarm" should stop beeping and start beeping again 5 minutes

  Examples: snooze a beeping alarm for a specific time
    | snooze for a time |
    | snooze for 5 minutes |
    | give me 10 minutes |

  Scenario Outline: user deletes an alarm when a single alarm is active
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on monday
     When the user says "<delete alarm>"
     Then "mycroft-alarm" should reply with dialog from "ask.cancel.desc.alarm.dialog"
     And the user says "yes"
     And "mycroft-alarm" should reply with dialog from "alarm.cancelled.desc.dialog"

  Examples: delete an alarm when a single alarm is active
    | delete alarm |
    | delete alarm |
    | cancel alarm |
    | disable alarm |
    | turn off alarm |
    | stop alarm |
    | abort alarm |
    | remove alarm |

  Scenario Outline: user starts to delete a single alarm but then cancels
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on monday
     When the user says "delete alarm"
     Then "mycroft-alarm" should reply with dialog from "ask.cancel.desc.alarm.dialog"
     And the user says "<no>"
     And "mycroft-alarm" should reply with dialog from "alarm.delete.cancelled.dialog"

  Examples: user starts to delete a single alarm but then cancels
    | no |
    | no |
    | nevermind |
    | forget it |
    | cancel |


  @xfail
  # Jira MS-74 https://mycroft.atlassian.net/browse/MS-74
  Scenario Outline: user deletes an alarm when multiple alarms are active
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on monday
     And an alarm is set for 10:00 pm on friday
     When the user says "<delete alarm>"
     Then "mycroft-alarm" should reply with dialog from "ask.which.alarm.delete.dialog"
     And the user says "9:00 am"
     And "mycroft-alarm" should reply with dialog from "ask.cancel.desc.alarm.dialog"
     And the user says "yes"
     And "mycroft-alarm" should reply with dialog from "alarm.cancelled.desc.dialog"

  Examples: delete an alarm when multiple alarm are active
    | delete alarm |
    | delete alarm |
    | cancel alarm |
    | disable alarm |
    | turn off alarm |
    | stop alarm |
    | abort alarm |
    | remove alarm |

  @xfail
  # Jira MS-75 https://mycroft.atlassian.net/browse/MS-75
  Scenario Outline: user deletes a specific alarm
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on monday
     And an alarm is set for 10:00 pm on friday
     When the user says "<delete specific alarm>"
     Then "mycroft-alarm" should reply with dialog from "ask.cancel.desc.alarm.dialog"
     And the user says "yes"
     And "mycroft-alarm" should reply with dialog from "alarm.cancelled.desc.dialog"

  Examples: delete an alarm when multiple alarm are active
    | delete specific alarm |
    | delete 9:00 am alarm |
    | cancel 9:00 am alarm |
    | disable 9:00 am alarm |
    | turn off 9:00 am alarm |
    | stop 9:00 am alarm |
    | abort 9:00 am alarm |
    | remove 9:00 am alarm |

  Scenario Outline: user deletes all alarms
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on monday
     And an alarm is set for 10:00 pm on friday
     When the user says "<delete all alarms>"
     Then "mycroft-alarm" should reply with dialog from "ask.cancel.alarm.plural.dialog"
     And the user says "yes"
     And "mycroft-alarm" should reply with dialog from "alarm.cancelled.multi.dialog"

  Examples: delete an alarm when multiple alarm are active
    | delete all alarms |
    | delete all alarms |
    | cancel all alarms |
    | remove all alarms |
    | turn off all alarms |
    | stop all alarms |
    | abort all alarms |
    | remove all alarms |
    | remove every alarm |
    | delete every alarm |

@xfail
Scenario Outline: user snoozes an alarm and then plays the news
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is expired and beeping
     When the user says "<snooze>"
     Then "mycroft-alarm" should stop beeping and start beeping again 10 minutes
     And the user says "play the news"
     And "skill-npr-news" should reply with dialog from "news.dialog"

  Examples: delete an alarm when multiple alarm are active
    | snooze |
    | snooze |
    | snooze alarm |
    | not yet |
    | 10 more minutes |
    | 10 minutes |
    | snooze for 10 minutes |
    | wake me up in 10 minutes |
    | remind me in 10 minutes |
    | let me sleep |
