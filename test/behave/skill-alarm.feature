Feature: Alarm

  Scenario Outline: User sets an Alarm
    Given an english speaking user
     When the user says "<set alarm for a time>"
     Then "skill-alarm"
