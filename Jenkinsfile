def commentOnPullRequest(msg) {
    withCredentials([string(
        credentialsId: "openshift-bot-token",
        variable: "GITHUB_TOKEN"
    )]) {
        script {
            writeFile(
                file: "msg.txt",
                text: msg
            )
            requestBody = sh(
                returnStdout: true,
                script: "jq --rawfile msg msg.txt -nr '{\"body\": \$msg}'"
            )
            repositoryName = env.GIT_URL
                .replace("https://github.com/", "")
                .replace(".git", "")

            httpRequest(
                contentType: 'APPLICATION_JSON',
                customHeaders: [[
                    maskValue: true,
                    name: 'Authorization',
                    value: "token ${env.GITHUB_TOKEN}"
                ]],
                httpMode: 'POST',
                requestBody: requestBody,
                responseHandle: 'NONE',
                url: "https://api.github.com/repos/${repositoryName}/issues/${env.CHANGE_ID}/comments"
            )
        }
    }
}

def publishToPyPI() {
    withCredentials([usernamePassword(
        credentialsId: "OpenShiftART_PyPI",
        usernameVariable: "TWINE_USERNAME",
        passwordVariable: "TWINE_PASSWORD"
    )]) {
        sh "python3 -m twine upload dist/*"
    }
}

pipeline {
    agent {
        docker {
            image "redhat/art-tools-ci:latest"
            args "--entrypoint=''"
        }
    }
    stages {
        stage("Tests & Coverage") {
            steps {
                script {
                    catchError(stageResult: 'FAILURE') {
                        sh "tox > results.txt 2>&1"
                    }
                    results = readFile("results.txt").trim()
                    echo results
                    commentOnPullRequest("### Build <span>#</span>${env.BUILD_NUMBER}\n```\n${results}\n```")
                }
            }
        }
        stage("Publish to PyPI") {
            when {
                branch "master"
            }
            steps {
                sh "python3 setup.py bdist_wheel --universal"
                sh "python3 -m twine check dist/*"
                script { publishToPyPI() }
            }
        }
    }
}
