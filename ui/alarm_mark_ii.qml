/*
 * Copyright 2018 by Aditya Mehra <aix.m@outlook.com>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 */
import QtQuick 2.12
import QtQuick.Controls 2.5
import QtQuick.Layouts 1.3
import QtGraphicalEffects 1.0

import Mycroft 1.0 as Mycroft


Mycroft.CardDelegate {
    id: alarmRoot
    cardBackgroundOverlayColor: "black"

    Item {
        id: alarmClockItem
        anchors.top: parent.top
        anchors.topMargin: gridUnit
        height: gridUnit * 20
        width: parent.width

        Image {
            id: alarmClockImage
            anchors.horizontalCenter: parent.horizontalCenter
            fillMode: Image.PreserveAspectFit
            height: parent.height
            source: "images/alarm-clock.svg"

            SequentialAnimation on opacity {
                id: expireAnimation
                running: sessionData.alarmExpired
                loops: Animation.Infinite
                PropertyAnimation {
                    from: 1;
                    to: 0;
                    duration: 500
                }

                PropertyAnimation {
                    from: 0;
                    to: 1;
                    duration: 500
                }
            }
        }

        AlarmLabel {
            id: alarmTime
            anchors.top: parent.top
            anchors.topMargin: gridUnit * 7
            fontSize: 100
            fontStyle: "Bold"
            heightUnits: 5
            text: sessionData.alarmTime
        }

        AlarmLabel {
            id: alarmAmPm
            anchors.top: alarmTime.bottom
            anchors.topMargin: gridUnit * 2
            fontSize: 47
            fontStyle: "Bold"
            heightUnits: 3
            text: sessionData.alarmAmPm
        }
    }

    AlarmLabel {
        id: alarmName
        anchors.bottom: parent.bottom
        anchors.bottomMargin: gridUnit * 2
        fontSize: 47
        fontStyle: "Bold"
        heightUnits: 3
        text: sessionData.alarmName
    }
}
